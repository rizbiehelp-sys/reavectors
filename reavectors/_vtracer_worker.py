"""
reavectors._vtracer_worker
==========================

Isolated subprocess that runs the native ``vtracer`` binding and writes an SVG.

It is launched as ``python <this file> IN OUT cm hier mode fs cp ld ct lt mi st pp``.

Why a subprocess?
-----------------
The current ``vtracer`` wheel has a bug where *keyword* arguments abort the
process (native access violation). Positional arguments work. Running it out of
process also means that if it ever crashes on a pathological input, only this
worker dies -- the caller (:mod:`reavectors.vtracer_engine`) sees a non-zero exit
and can fall back to the Potrace engine.

Exit codes: 0 ok, 3 vtracer unavailable, 4 conversion error, 2 bad args.
"""

from __future__ import annotations

import sys

# vtracer positional order: colormode, hierarchical, mode, filter_speckle,
# color_precision, layer_difference, corner_threshold, length_threshold,
# max_iterations, splice_threshold, path_precision
_STR = slice(0, 3)
_INT = (3, 4, 5, 6, 8, 9, 10)
_FLOAT = (7,)


def main(argv) -> int:
    if len(argv) != 13:
        print("usage: worker IN OUT cm hier mode fs cp ld ct lt mi st pp", file=sys.stderr)
        return 2
    in_path, out_path = argv[0], argv[1]
    raw = argv[2:]

    params = list(raw)
    try:
        for i in _INT:
            params[i] = int(params[i])
        for i in _FLOAT:
            params[i] = float(params[i])
    except (ValueError, IndexError) as e:
        print(f"bad numeric argument: {e}", file=sys.stderr)
        return 2

    try:
        import vtracer
    except ImportError:
        print("vtracer not installed", file=sys.stderr)
        return 3

    try:
        vtracer.convert_image_to_svg_py(in_path, out_path, *params)
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
