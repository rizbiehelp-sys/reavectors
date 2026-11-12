"""
reavectors.svgparse
===================

A small SVG reader used for *export*: it turns an engine's SVG output (e.g. the
SVG produced by vtracer) back into the geometry model
(:class:`~reavectors.vectorize.Layer` / :class:`Figure` / :class:`Contour`) so the
same paths can be written to PDF/AI and EPS.

It understands the core SVG path grammar: M/m L/l H/h V/v C/c S/s Q/q T/t Z/z,
including implicit repeated commands and relative coordinates. Quadratic and
smooth curves are normalised to cubic Béziers. Arcs (A/a) are intentionally not
handled (neither engine emits them).
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .vectorize import Contour, Figure, Layer

_NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZz]|" + _NUM)

PathElem = re.compile(r"<path\b[^>]*>", re.IGNORECASE)
_ATTR_D = re.compile(r'\bd\s*=\s*"([^"]*)"')
_ATTR_FILL = re.compile(r'\bfill\s*=\s*"([^"]*)"')
_ATTR_OPACITY = re.compile(r'\bfill-opacity\s*=\s*"([^"]*)"')
_ATTR_TRANSFORM = re.compile(r'\btransform\s*=\s*"([^"]*)"')
_VIEWBOX = re.compile(r'\bviewBox\s*=\s*"([^"]*)"')
_WIDTH = re.compile(r'\bwidth\s*=\s*"([0-9.]+)')
_HEIGHT = re.compile(r'\bheight\s*=\s*"([0-9.]+)')
_TRANSFORM_FN = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")

# 2D affine transform as (a, b, c, d, e, f):  x' = a*x + c*y + e ; y' = b*x + d*y + f
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(m, n):
    """Compose two affines: result = m ∘ n (n applied first)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(value: str):
    """Parse an SVG transform list into a single affine matrix."""
    m = _IDENTITY
    for name, argstr in _TRANSFORM_FN.findall(value or ""):
        nums = [float(x) for x in re.split(r"[,\s]+", argstr.strip()) if x]
        name = name.lower()
        if name == "translate":
            tx = nums[0] if nums else 0.0
            ty = nums[1] if len(nums) > 1 else 0.0
            m = _mul(m, (1, 0, 0, 1, tx, ty))
        elif name == "scale":
            sx = nums[0] if nums else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            m = _mul(m, (sx, 0, 0, sy, 0, 0))
        elif name == "matrix" and len(nums) == 6:
            m = _mul(m, tuple(nums))
        elif name == "rotate" and nums:
            import math
            ang = math.radians(nums[0])
            ca, sa = math.cos(ang), math.sin(ang)
            r = (ca, sa, -sa, ca, 0, 0)
            if len(nums) == 3:  # rotate about a point
                r = _mul(_mul((1, 0, 0, 1, nums[1], nums[2]), r),
                         (1, 0, 0, 1, -nums[1], -nums[2]))
            m = _mul(m, r)
    return m


def _apply(matrix, contour: Contour) -> Contour:
    a, b, c, d, e, f = matrix
    def p(x, y):
        return (a * x + c * y + e, b * x + d * y + f)
    out = Contour(start=p(*contour.start))
    for seg in contour.segments:
        if seg[0] == "L":
            out.segments.append(("L", p(*seg[1])))
        else:
            _, c1, c2, en = seg
            out.segments.append(("C", p(*c1), p(*c2), p(*en)))
    return out


def _parse_color(value: str):
    """'#rgb' | '#rrggbb' | '#rrggbbaa' | 'rgb(...)' -> (r,g,b) or None."""
    if not value:
        return None
    v = value.strip().lower()
    if v in ("none", "transparent"):
        return None
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"rgba?\(([^)]+)\)", v)
    if m:
        parts = re.split(r"[,\s]+", m.group(1).strip())
        try:
            r, g, b = (int(float(parts[i])) for i in range(3))
            return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
        except (ValueError, IndexError):
            return None
    return None


def parse_path(d: str) -> List[Contour]:
    """Parse an SVG path 'd' string into a list of cubic Contours."""
    tokens = _TOKEN.findall(d)
    contours: List[Contour] = []
    cur: Contour | None = None

    cx = cy = sx = sy = 0.0
    last_ctrl = (0.0, 0.0)
    prev_cmd = ""
    i = 0
    n = len(tokens)

    def start_new(x, y):
        nonlocal cur
        cur = Contour(start=(x, y))
        contours.append(cur)

    while i < n:
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
        else:
            # implicit repeat: M becomes L, m becomes l, others repeat
            if prev_cmd in ("M", "m"):
                cmd = "L" if prev_cmd == "M" else "l"
            else:
                cmd = prev_cmd
        prev_cmd = cmd

        def take(k):
            nonlocal i
            vals = [float(tokens[i + j]) for j in range(k)]
            i += k
            return vals

        if cmd in ("M", "m"):
            x, y = take(2)
            if cmd == "m":
                x, y = cx + x, cy + y
            cx, cy = sx, sy = x, y
            start_new(x, y)
        elif cmd in ("L", "l"):
            x, y = take(2)
            if cmd == "l":
                x, y = cx + x, cy + y
            cur.segments.append(("L", (x, y)))
            cx, cy = x, y
        elif cmd in ("H", "h"):
            (x,) = take(1)
            x = cx + x if cmd == "h" else x
            cur.segments.append(("L", (x, cy)))
            cx = x
        elif cmd in ("V", "v"):
            (y,) = take(1)
            y = cy + y if cmd == "v" else y
            cur.segments.append(("L", (cx, y)))
            cy = y
        elif cmd in ("C", "c"):
            x1, y1, x2, y2, x, y = take(6)
            if cmd == "c":
                x1, y1, x2, y2, x, y = cx + x1, cy + y1, cx + x2, cy + y2, cx + x, cy + y
            cur.segments.append(("C", (x1, y1), (x2, y2), (x, y)))
            last_ctrl = (x2, y2)
            cx, cy = x, y
        elif cmd in ("S", "s"):
            x2, y2, x, y = take(4)
            if cmd == "s":
                x2, y2, x, y = cx + x2, cy + y2, cx + x, cy + y
            # reflect previous control point
            x1, y1 = (2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1])
            cur.segments.append(("C", (x1, y1), (x2, y2), (x, y)))
            last_ctrl = (x2, y2)
            cx, cy = x, y
        elif cmd in ("Q", "q"):
            qx, qy, x, y = take(4)
            if cmd == "q":
                qx, qy, x, y = cx + qx, cy + qy, cx + x, cy + y
            # quadratic -> cubic
            c1 = (cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy))
            c2 = (x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y))
            cur.segments.append(("C", c1, c2, (x, y)))
            last_ctrl = (qx, qy)
            cx, cy = x, y
        elif cmd in ("T", "t"):
            x, y = take(2)
            if cmd == "t":
                x, y = cx + x, cy + y
            qx, qy = (2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1])
            c1 = (cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy))
            c2 = (x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y))
            cur.segments.append(("C", c1, c2, (x, y)))
            last_ctrl = (qx, qy)
            cx, cy = x, y
        elif cmd in ("Z", "z"):
            if cur is not None:
                cx, cy = sx, sy
        else:
            # unknown token; stop to avoid an infinite loop
            i += 1

    return [c for c in contours if c.segments]


def parse_svg(svg: str) -> Tuple[int, int, List[Layer]]:
    """Return (width, height, layers) from an SVG string."""
    width = height = 0
    vb = _VIEWBOX.search(svg)
    if vb:
        parts = re.split(r"[,\s]+", vb.group(1).strip())
        try:
            width, height = int(float(parts[2])), int(float(parts[3]))
        except (ValueError, IndexError):
            pass
    if not width:
        mw = _WIDTH.search(svg)
        mh = _HEIGHT.search(svg)
        width = int(float(mw.group(1))) if mw else 0
        height = int(float(mh.group(1))) if mh else 0

    by_color: "dict[tuple, Layer]" = {}
    for elem in PathElem.findall(svg):
        dm = _ATTR_D.search(elem)
        if not dm:
            continue
        color = _parse_color(_ATTR_FILL.search(elem).group(1) if _ATTR_FILL.search(elem) else "")
        if color is None:
            continue
        contours = parse_path(dm.group(1))
        if not contours:
            continue
        # Apply the element's transform (vtracer places every path with a
        # translate()). Without this the geometry is offset/flipped and any
        # PDF/EPS export would be wrong.
        tm = _ATTR_TRANSFORM.search(elem)
        if tm:
            matrix = _parse_transform(tm.group(1))
            if matrix != _IDENTITY:
                contours = [_apply(matrix, c) for c in contours]
        fig = Figure(contours=contours)
        layer = by_color.get(color)
        if layer is None:
            layer = Layer(color=color)
            by_color[color] = layer
        layer.figures.append(fig)

    return width, height, list(by_color.values())
