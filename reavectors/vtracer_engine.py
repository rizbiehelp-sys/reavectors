"""
reavectors.vtracer_engine
=========================

Runs the native ``vtracer`` colour vectoriser out-of-process and returns its SVG.

``vtracer`` (visioncortex) is a modern multi-colour vectoriser that produces
noticeably cleaner colour output than tracing one flat mask per palette colour
by hand. It is used as the default engine; :mod:`reavectors.vectorize` falls
back to Potrace when it is unavailable or fails.

Availability is probed once and cached. Tuning happens through named *styles*
because the wheel's positional API is the only one that is stable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vtracer_worker.py")

# Named parameter sets. Keys map to vtracer's positional order.
#   colormode, hierarchical, mode, filter_speckle, color_precision,
#   layer_difference, corner_threshold, length_threshold, max_iterations,
#   splice_threshold, path_precision
STYLES = {
    # Flat art: logos, icons, stickers. Snaps anti-aliasing to clean colour.
    "logo": {
        "colormode": "color", "hierarchical": "stacked", "mode": "spline",
        "filter_speckle": 4, "color_precision": 6, "layer_difference": 16,
        "corner_threshold": 60, "length_threshold": 4.0, "max_iterations": 10,
        "splice_threshold": 45, "path_precision": 2,
    },
    # Gradients / photographic: many thin colour layers, low merge threshold.
    "photo": {
        "colormode": "color", "hierarchical": "stacked", "mode": "spline",
        "filter_speckle": 2, "color_precision": 8, "layer_difference": 4,
        "corner_threshold": 60, "length_threshold": 4.0, "max_iterations": 10,
        "splice_threshold": 45, "path_precision": 2,
    },
    # Silhouettes / line art / cut files: two-tone.
    "line": {
        "colormode": "binary", "hierarchical": "stacked", "mode": "spline",
        "filter_speckle": 8, "color_precision": 6, "layer_difference": 16,
        "corner_threshold": 60, "length_threshold": 4.0, "max_iterations": 10,
        "splice_threshold": 45, "path_precision": 2,
    },
}

_ORDER = ["colormode", "hierarchical", "mode", "filter_speckle", "color_precision",
          "layer_difference", "corner_threshold", "length_threshold",
          "max_iterations", "splice_threshold", "path_precision"]

_available: "bool | None" = None


def available() -> bool:
    """True if the vtracer binding imports (checked once)."""
    global _available
    if _available is None:
        try:
            import vtracer  # noqa: F401
            _available = True
        except Exception:  # noqa: BLE001
            _available = False
    return _available


def run(image_path: str, style: str = "logo", detail: int | None = None,
        overrides: "dict | None" = None, timeout: int = 180) -> "str | None":
    """
    Vectorise ``image_path`` with vtracer. Returns the SVG text or ``None`` if
    vtracer is unavailable, fails, or times out (caller should fall back).

    ``detail`` (optional) overrides ``layer_difference``: smaller = more colour
    layers = more detail in gradients. ``overrides`` may set any of the named
    style keys (used by the refiner to vary colour precision, path precision,
    etc.).
    """
    if not available():
        return None

    params = dict(STYLES.get(style, STYLES["logo"]))
    if detail is not None:
        params["layer_difference"] = max(0, int(detail))
    if overrides:
        params.update({k: v for k, v in overrides.items() if k in params})

    out_fd, out_path = tempfile.mkstemp(suffix=".svg")
    os.close(out_fd)
    argv = [sys.executable, _WORKER, image_path, out_path] + [str(params[k]) for k in _ORDER]

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        with open(out_path, "r", encoding="utf-8") as f:
            svg = f.read()
        return svg if "<svg" in svg else None
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass
