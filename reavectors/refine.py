"""
reavectors.refine
=================

A time-budgeted, closed-loop refiner.

It repeatedly re-traces the input at increasing levels of detail, rasterises
each candidate back to pixels, measures how well it matches the source, and
keeps the best result. It stops when the time budget is spent (or the schedule
is exhausted), so a caller can spend e.g. ~10 seconds of CPU to get a more
detailed result than a single pass.

This is a genuine quality/size trade-off, not a sleep: every iteration actually
tries harder (more colour layers, higher colour precision, finer path
coordinates, optional super-sampling) and keeps it only if the measured match
improves.

Metrics
-------
``match`` is the percentage of pixels (RGBA) whose channels are all within
``tolerance`` of the source. It is measured on a downscaled copy for speed so it
is stable and comparable between candidates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from .vectorize import VectorResult, vectorize, _load_rgba
from .vtracer_engine import STYLES

_SCORE_DIM = 256      # rasterise candidates at this longest edge for scoring
_FLATTEN_STEPS = 10   # bezier -> polyline resolution for rasterisation


# ---------------------------------------------------------------------------
# rasterisation + scoring
# ---------------------------------------------------------------------------
def _flatten(contour, steps: int = _FLATTEN_STEPS):
    pts = [contour.start]
    cur = contour.start
    for seg in contour.segments:
        if seg[0] == "L":
            cur = seg[1]
            pts.append(cur)
        else:
            _, c1, c2, e = seg
            for i in range(1, steps + 1):
                t = i / steps
                mt = 1 - t
                x = (mt ** 3) * cur[0] + 3 * (mt ** 2) * t * c1[0] + 3 * mt * (t ** 2) * c2[0] + (t ** 3) * e[0]
                y = (mt ** 3) * cur[1] + 3 * (mt ** 2) * t * c1[1] + 3 * mt * (t ** 2) * c2[1] + (t ** 3) * e[1]
                pts.append((x, y))
            cur = e
    return pts


def rasterize(result: VectorResult, out_dim: int = _SCORE_DIM) -> np.ndarray:
    """
    Rasterise a result to an RGBA array (longest edge == out_dim).

    Each figure's subpaths are XOR-composited, which implements even-odd filling
    (equivalent to nonzero for the simple nested shapes both engines emit).
    """
    W = max(1, result.width)
    H = max(1, result.height)
    s = out_dim / max(W, H)
    ow, oh = max(1, round(W * s)), max(1, round(H * s))
    canvas = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))

    for layer in result.layers:
        if not layer.figures:
            continue
        mask = Image.new("1", (ow, oh), 0)
        drew = False
        for fig in layer.figures:
            for contour in fig.contours:
                poly = [(x * s, y * s) for (x, y) in _flatten(contour)]
                if len(poly) < 3:
                    continue
                tmp = Image.new("1", (ow, oh), 0)
                ImageDraw.Draw(tmp).polygon(poly, fill=1)
                mask = ImageChops.logical_xor(mask, tmp)
                drew = True
        if not drew:
            continue
        color = Image.new("RGBA", (ow, oh), tuple(layer.color) + (255,))
        canvas = Image.composite(color, canvas, mask)

    return np.asarray(canvas, dtype=np.uint8)


def _reference_rgba(source, out_dim: int = _SCORE_DIM) -> np.ndarray:
    img = _load_rgba(source)
    W, H = img.size
    s = out_dim / max(W, H)
    img = img.resize((max(1, round(W * s)), max(1, round(H * s))), Image.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


def match_score(reference: np.ndarray, candidate: np.ndarray, tolerance: int = 32) -> float:
    """Percent of RGBA pixels matching within ``tolerance`` (0..100)."""
    if reference.shape != candidate.shape:
        h = min(reference.shape[0], candidate.shape[0])
        w = min(reference.shape[1], candidate.shape[1])
        reference = reference[:h, :w]
        candidate = candidate[:h, :w]
    diff = np.abs(reference.astype(np.int16) - candidate.astype(np.int16))
    good = (diff <= tolerance).all(axis=2)
    return 100.0 * float(good.mean())


# ---------------------------------------------------------------------------
# candidate schedule + loop
# ---------------------------------------------------------------------------
@dataclass
class RefineStats:
    iterations: int = 0
    seconds: float = 0.0
    best_match: float = 0.0
    best_profile: dict = field(default_factory=dict)
    history: List[dict] = field(default_factory=list)


def _schedule(style: str, ss_factors=(1,)):
    """
    Build an increasing-detail search order. Coarse passes run first (cheap) so
    the refiner always has a good result early, then finer and structurally
    different passes compete for the remaining time budget. Every knob here is
    one the fidelity metric can actually measure (colour layers, colour
    precision, path precision, corner threshold, speckle filter, tracing mode,
    hierarchy), so the budget is spent on changes that can win.
    """
    base = STYLES.get(style, STYLES["logo"])
    ld0 = int(base["layer_difference"])
    cp0 = int(base["color_precision"])

    lds = sorted({ld0, max(1, ld0 // 2), max(1, ld0 // 3), max(1, ld0 // 4),
                  max(1, ld0 // 6), max(1, ld0 // 8), 2, 1}, reverse=True)

    out = []
    seen = set()

    def add(ld, cp, pp, ss=1, extra=None):
        extra = extra or {}
        key = (ld, cp, pp, ss, tuple(sorted(extra.items())))
        if key in seen:
            return
        seen.add(key)
        prof = {"layer_difference": ld, "color_precision": cp,
                "path_precision": pp, "supersample": ss}
        prof.update(extra)
        out.append(prof)

    # 1) colour-layer sweep at the base colour precision (cheap -> fine)
    for ld in lds:
        add(ld, cp0, 2)
    # 2) same sweep at max colour precision / finer coordinates
    for ld in lds:
        add(ld, 8, 3)
    add(1, 8, 4)
    # 3) structural variations at high detail
    add(1, 8, 3, extra={"corner_threshold": 30})   # keep more corners
    add(1, 8, 3, extra={"corner_threshold": 90})   # smoother
    add(1, 8, 3, extra={"filter_speckle": 0})      # keep tiny regions
    add(1, 8, 3, extra={"filter_speckle": 8})      # drop tiny regions
    add(1, 8, 3, extra={"splice_threshold": 30})
    add(1, 8, 3, extra={"length_threshold": 2.0})
    add(1, 8, 3, extra={"mode": "polygon"})
    add(max(1, ld0 // 2), 8, 3, extra={"hierarchical": "cutout"})
    add(1, 8, 3, extra={"hierarchical": "cutout"})
    # 4) super-sampled passes last (only the largest allowed factor)
    if max(ss_factors) > 1:
        add(1, 8, 3, ss=max(ss_factors))
    return out


def auto_refine(
    source,
    budget: float = 10.0,
    style: str = "logo",
    tolerance: int = 32,
    max_iterations: int = 24,
    max_size: int = 1100,
    on_progress=None,
) -> "tuple[VectorResult, RefineStats]":
    """
    Iteratively improve a trace within ``budget`` seconds.

    Returns ``(best_result, stats)``. Always returns at least one result (the
    first candidate) even if it cannot improve or runs out of time.
    """
    from . import vtracer_engine

    reference = _reference_rgba(source)

    # Decide how far we can afford to super-sample, based on the *effective*
    # trace size (after any max_size downscale), not the max_size cap.
    probe = _load_rgba(source)
    eff = max(probe.size)
    if max_size and eff > max_size:
        eff = max_size
    # Cap the super-sampled trace so one slow pass can't dominate the budget.
    ss_cap = 1200
    ss_factors = [f for f in (1, 2, 3, 4) if eff * f <= ss_cap] or [1]

    started = time.monotonic()
    stats = RefineStats()

    def remaining() -> float:
        return budget - (time.monotonic() - started)

    best_result: "Optional[VectorResult]" = None
    best_score = -1.0

    # If vtracer is unavailable, fall back to a single Potrace pass with a small
    # palette sweep so the loop is still meaningful.
    if not vtracer_engine.available():
        for colors in (6, 12, 24):
            if remaining() <= 0 and best_result is not None:
                break
            result = vectorize(source, engine="potrace", colors=colors, max_size=max_size)
            score = match_score(reference, rasterize(result), tolerance)
            stats.iterations += 1
            stats.history.append({"colors": colors, "match": round(score, 2)})
            if on_progress:
                on_progress(stats.iterations, round(score, 2), "potrace")
            if score > best_score:
                best_score, best_result = score, result
                stats.best_profile = {"colors": colors}
        stats.seconds = time.monotonic() - started
        stats.best_match = round(max(best_score, 0.0), 2)
        return best_result, stats

    for profile in _schedule(style, ss_factors=ss_factors)[:max_iterations]:
        left = remaining()
        if left <= 0.5 and best_result is not None:
            break
        ss = profile["supersample"]
        overrides = {k: v for k, v in profile.items() if k != "supersample"}
        t0 = time.monotonic()
        result = vectorize(
            source, engine="vtracer", style=style, max_size=max_size,
            supersample=ss, timeout=max(5, int(left)), vtracer_params=overrides,
        )
        score = match_score(reference, rasterize(result), tolerance)
        dt = time.monotonic() - t0
        stats.iterations += 1
        stats.history.append({
            "layer_difference": profile["layer_difference"],
            "color_precision": profile["color_precision"],
            "supersample": ss, "match": round(score, 2), "seconds": round(dt, 2),
        })
        if on_progress:
            on_progress(stats.iterations, round(score, 2), result.engine)
        if score > best_score:
            best_score, best_result = score, result
            stats.best_profile = dict(profile)

    stats.seconds = time.monotonic() - started
    stats.best_match = round(max(best_score, 0.0), 2)
    if best_result is None:
        best_result = vectorize(source, engine="auto", style=style, max_size=max_size)
    return best_result, stats
