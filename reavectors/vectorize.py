"""
reavectors.vectorize
====================

Core engine: turn a (transparent) PNG into vector geometry.

Design
------
* No proprietary models or third-party SaaS. Tracing is done with ``potracer``
  (a pure-Python port of Potrace) which converts binary bitmaps into smooth
  Bezier outlines.
* Colour is handled by quantising the opaque pixels into a small palette and
  tracing one binary mask per palette colour. Each mask is AND-ed with the
  opacity mask, so the transparent background is simply *never traced* and stays
  transparent in the output.
* The result is a resolution-independent structure (layers -> figures ->
  contours -> segments) that can be serialised to SVG, PDF or EPS/AI.

Everything here is deterministic and offline.
"""

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import numpy as np
from PIL import Image

try:
    import potrace
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "reavectors needs 'potracer'. Install with: pip install potracer"
    ) from exc

Point = Tuple[float, float]
# A segment is either ("L", end) or ("C", c1, c2, end)
Segment = Tuple


@dataclass
class Contour:
    """One closed subpath: a start point plus a list of segments."""
    start: Point
    segments: List[Segment] = field(default_factory=list)


@dataclass
class Figure:
    """A filled region: one outer contour plus zero or more hole contours."""
    contours: List[Contour] = field(default_factory=list)


@dataclass
class Layer:
    """All geometry drawn in a single flat colour."""
    color: Tuple[int, int, int]
    figures: List[Figure] = field(default_factory=list)
    opacity: float = 1.0


@dataclass
class VectorResult:
    """A finished vector document (independent of output format)."""
    width: int
    height: int
    layers: List[Layer]
    source: str = ""            # short human label, e.g. original filename
    engine: str = ""            # which engine produced this ("vtracer"/"potrace")
    fill_rule: str = "evenodd"  # "evenodd" (potrace) or "nonzero" (vtracer)
    svg_override: Optional[str] = None  # engine-native SVG, used verbatim if set

    # -- small helpers ------------------------------------------------------
    @property
    def color_count(self) -> int:
        return len([l for l in self.layers if l.figures])

    @property
    def path_count(self) -> int:
        return sum(len(fig.contours) for l in self.layers for fig in l.figures)

    @property
    def figure_count(self) -> int:
        return sum(len(l.figures) for l in self.layers)

    # -- serialisation ------------------------------------------------------
    def to_svg(self, precision: int = 3) -> str:
        """
        Serialise to an SVG string with a transparent background.

        If the engine supplied its own SVG (e.g. vtracer), that is returned
        verbatim so the web preview reflects exactly what the engine drew.
        """
        if self.svg_override:
            return self.svg_override
        fmt = _num(precision)
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" '
            f'shape-rendering="geometricPrecision">',
        ]
        for layer in self.layers:
            if not layer.figures:
                continue
            d = " ".join(_contour_to_svg(c, fmt) for fig in layer.figures for c in fig.contours)
            hexcol = "#%02X%02X%02X" % layer.color
            opacity = ""
            if layer.opacity < 0.999:
                opacity = f' fill-opacity="{_num(3)(layer.opacity)}"'
            parts.append(
                f'<path d="{d}" fill="{hexcol}"{opacity} '
                f'fill-rule="{self.fill_rule}" clip-rule="{self.fill_rule}"/>'
            )
        parts.append("</svg>")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Potrace curve -> our geometry
# ---------------------------------------------------------------------------

def _curve_to_contour(curve) -> Contour:
    """Convert one potrace curve (outer or hole) into a Contour."""
    start = curve.start_point
    contour = Contour(start=(start.x, start.y))
    for seg in curve.segments:
        if seg.is_corner:
            c = seg.c
            contour.segments.append(("L", (c.x, c.y)))
        else:
            c1, c2, e = seg.c1, seg.c2, seg.end_point
            contour.segments.append(
                ("C", (c1.x, c1.y), (c2.x, c2.y), (e.x, e.y))
            )
    return contour


def _curve_to_figure(curve) -> Figure:
    """A potrace curve plus its children become one Figure (outer + holes)."""
    fig = Figure(contours=[_curve_to_contour(curve)])
    children = curve.children or []
    for child in children:
        child_fig = _curve_to_figure(child)
        fig.contours.extend(child_fig.contours)
    return fig


def _trace_mask(mask: np.ndarray, turdsize: int, alphamax: float,
                opttolerance: float) -> List[Figure]:
    """
    Trace a boolean mask into figures. Empty mask -> no figures.

    Orientation note: Potrace treats *dark* pixels as the foreground. potracer's
    ``Bitmap.__init__`` thresholds the input with ``data > 255*blacklevel`` and
    then calls ``invert()``, so the net rule is "foreground = value <=
    threshold". We therefore encode the shape as a dark value (0) and the
    background as a bright value (255); feeding a 0/1 mask directly leaves the
    whole bitmap as foreground.
    """
    if not mask.any():
        return []
    bitmap = np.where(mask, 0, 255).astype(np.uint8)
    bmp = potrace.Bitmap(bitmap, blacklevel=0.5)
    path = bmp.trace(
        turdsize=int(turdsize),
        turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
        alphamax=float(alphamax),
        opticurve=True,
        opttolerance=float(opttolerance),
    )
    return [_curve_to_figure(c) for c in path.curves]


# ---------------------------------------------------------------------------
# Image analysis
# ---------------------------------------------------------------------------

def _load_rgba(source) -> Image.Image:
    """Accept a path, bytes, file-like or PIL image and return RGBA."""
    if isinstance(source, Image.Image):
        img = source
    elif isinstance(source, (bytes, bytearray)):
        img = Image.open(io.BytesIO(bytes(source)))
    elif hasattr(source, "read"):
        img = Image.open(source)
    else:
        img = Image.open(source)
    return img.convert("RGBA")


def _downscale(img: Image.Image, max_size: int) -> Tuple[Image.Image, float]:
    """Downscale so the longest edge <= max_size (keeps aspect). Returns scale."""
    w, h = img.size
    longest = max(w, h)
    if max_size and longest > max_size:
        scale = max_size / longest
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                         Image.LANCZOS)
        return img, scale
    return img, 1.0


def _try_vtracer(img: Image.Image, W: int, H: int, style: str,
                 detail: Optional[int], timeout: int = 180,
                 overrides: "Optional[dict]" = None) -> "Optional[VectorResult]":
    """Run vtracer in a subprocess and parse its SVG. None on any failure."""
    from . import vtracer_engine

    if not vtracer_engine.available():
        return None
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        img.save(path, "PNG")
        svg = vtracer_engine.run(path, style=style, detail=detail,
                                 overrides=overrides, timeout=timeout)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not svg:
        return None
    try:
        from .svgparse import parse_svg
        w, h, layers = parse_svg(svg)
    except Exception:  # noqa: BLE001 - a parse failure just means "use fallback"
        return None
    if not layers:
        return None
    return VectorResult(width=w or W, height=h or H, layers=layers,
                        engine="vtracer", fill_rule="nonzero", svg_override=svg)


def vectorize(
    source,
    engine: str = "auto",
    style: str = "logo",
    detail: Optional[int] = None,
    colors: int = 8,
    alpha_threshold: int = 128,
    turdsize: int = 2,
    alphamax: float = 1.0,
    opttolerance: float = 0.2,
    max_size: int = 1600,
    min_region: int = 0,
    supersample: int = 1,
    timeout: int = 180,
    vtracer_params: "Optional[dict]" = None,
) -> VectorResult:
    """
    Vectorise a transparent image.

    Parameters
    ----------
    source : path | bytes | file | PIL.Image
        The input image. Alpha is treated as the silhouette.
    engine : {"auto", "vtracer", "potrace"}
        "auto" (default) uses vtracer when available and falls back to Potrace.
        vtracer: multi-colour, best quality. potrace: flat-mask tracing.
    style : {"logo", "photo", "line"}
        vtracer tuning preset. "logo" for flat art, "photo" for gradients,
        "line" for two-tone silhouettes.
    detail : int | None
        Optional vtracer ``layer_difference`` override (smaller = more colour
        layers = more gradient detail).
    colors, alpha_threshold, turdsize, alphamax, opttolerance, max_size,
    min_region : legacy Potrace-engine controls (also used for the fallback).

    Returns
    -------
    VectorResult
    """
    img = _load_rgba(source)
    img, _ = _downscale(img, max_size)
    W, H = img.size

    # Supersampling: trace at Nx resolution, then scale geometry back down to
    # the display size. Costs time/memory but yields finer, smoother outlines.
    ss = max(1, int(supersample))
    trace_img = img if ss == 1 else img.resize((W * ss, H * ss), Image.LANCZOS)

    # ---- primary engine: vtracer (out-of-process, crash-isolated) ----------
    if engine in ("auto", "vtracer"):
        result = _try_vtracer(trace_img, W * ss, H * ss, style, detail, timeout,
                              vtracer_params)
        if result is not None:
            return _finish(result, W, H, ss)


    rgba = np.asarray(trace_img, dtype=np.uint8)
    alpha = rgba[:, :, 3]
    opaque = alpha >= int(alpha_threshold)

    if not opaque.any():
        # fully transparent -> empty document
        return _finish(VectorResult(width=W * ss, height=H * ss, layers=[],
                                    engine="potrace"), W, H, ss)

    rgb = rgba[:, :, :3]

    # Fill transparent pixels with the median opaque colour so the quantiser's
    # palette reflects only real content and does not invent a phantom colour.
    fill = np.median(rgb[opaque], axis=0).astype(np.uint8)
    rgb_filled = rgb.copy()
    rgb_filled[~opaque] = fill

    ncolors = max(1, min(256, int(colors)))
    pil_rgb = Image.fromarray(rgb_filled, mode="RGB")
    q = pil_rgb.quantize(colors=ncolors, method=Image.MEDIANCUT, dither=Image.NONE)
    palette = q.getpalette() or []
    idx = np.asarray(q, dtype=np.int32)

    layers: List[Layer] = []
    for k in range(ncolors):
        mask = opaque & (idx == k)
        count = int(mask.sum())
        if count == 0:
            continue
        if min_region and count < min_region:
            continue
        base = k * 3
        if base + 2 >= len(palette):
            break
        color = (int(palette[base]), int(palette[base + 1]), int(palette[base + 2]))
        figures = _trace_mask(mask, turdsize, alphamax, opttolerance)
        if figures:
            layers.append(Layer(color=color, figures=figures))

    if not layers:
        return _finish(VectorResult(width=W * ss, height=H * ss, layers=[],
                                    engine="potrace"), W, H, ss)
    return _finish(VectorResult(width=W * ss, height=H * ss, layers=layers,
                                engine="potrace"), W, H, ss)


def _scale_result(result: VectorResult, factor: float) -> None:
    """Scale every coordinate in a result in place (used to un-supersample)."""
    def sx(v):
        return v * factor

    for layer in result.layers:
        for fig in layer.figures:
            for contour in fig.contours:
                contour.start = (contour.start[0] * factor, contour.start[1] * factor)
                new_segs = []
                for seg in contour.segments:
                    if seg[0] == "L":
                        e = seg[1]
                        new_segs.append(("L", (e[0] * factor, e[1] * factor)))
                    else:
                        _, c1, c2, e = seg
                        new_segs.append(("C",
                                         (c1[0] * factor, c1[1] * factor),
                                         (c2[0] * factor, c2[1] * factor),
                                         (e[0] * factor, e[1] * factor)))
                contour.segments = new_segs


def _finish(result: VectorResult, W: int, H: int, ss: int) -> VectorResult:
    """Un-supersample a result and reset it to the display canvas size."""
    if ss > 1:
        _scale_result(result, 1.0 / ss)
        result.width, result.height = W, H
        result.svg_override = None  # geometry was rescaled; rebuild SVG from it
    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _num(precision: int):
    def f(value) -> str:
        s = f"{float(value):.{precision}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"
    return f


def _contour_to_svg(contour: Contour, fmt) -> str:
    x, y = contour.start
    out = [f"M{fmt(x)} {fmt(y)}"]
    for seg in contour.segments:
        if seg[0] == "L":
            out.append(f"L{fmt(seg[1][0])} {fmt(seg[1][1])}")
        else:
            _, c1, c2, e = seg
            out.append(
                f"C{fmt(c1[0])} {fmt(c1[1])} {fmt(c2[0])} {fmt(c2[1])} "
                f"{fmt(e[0])} {fmt(e[1])}"
            )
    out.append("Z")
    return "".join(out)
