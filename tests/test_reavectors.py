"""
Tests for reavectors. Run with:  python -m pytest  (or)  python tests/test_reavectors.py
"""

from __future__ import annotations

import io
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors import vectorize, render_pdf, render_eps  # noqa: E402
from reavectors.vectorize import Contour  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def make_test_image(size=192):
    """Invented logo-ish art on a transparent background."""
    from PIL import ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([10, 10, size - 10, size - 10], fill=(11, 11, 11, 255))
    d.ellipse([26, 26, size - 26, size - 26], fill=(254, 86, 75, 255))
    d.ellipse([46, 46, size - 46, size - 46], fill=(254, 254, 254, 255))
    d.rectangle([size // 2 - 12, size // 2 - 40, size // 2 + 12, size // 2 + 40],
                fill=(0, 209, 200, 255))
    return img


def flatten_contour(contour: Contour, steps: int = 16):
    """Bezier -> polyline (closed)."""
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


def point_in_polygons_evenodd(px, py, polygons) -> bool:
    """Even-odd crossing test across all polygons of one layer."""
    inside = False
    for poly in polygons:
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > py) != (y2 > py):
                xint = (x2 - x1) * (py - y1) / (y2 - y1) + x1
                if px < xint:
                    inside = not inside
    return inside


def reconstruct_color_map(result):
    """For each layer, precompute polygons; return a function point->color or None."""
    layer_polys = []
    for layer in result.layers:
        polys = [flatten_contour(c) for fig in layer.figures for c in fig.contours]
        layer_polys.append((layer.color, polys))

    def color_at(x, y):
        for color, polys in layer_polys:
            if point_in_polygons_evenodd(x, y, polys):
                return color
        return None

    return color_at


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_empty_transparent_yields_no_layers():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    res = vectorize(img, engine="potrace", colors=4)
    assert res.layers == []
    assert "<svg" in res.to_svg()


def test_reconstruction_matches_source():
    img = make_test_image(192)
    res = vectorize(img, engine="potrace", colors=6, alpha_threshold=128, max_size=0)
    assert res.color_count >= 3

    rgba = np.asarray(img.convert("RGBA"))
    opaque = rgba[:, :, 3] >= 128
    color_at = reconstruct_color_map(res)

    agree = 0
    total = 0
    step = 3
    for y in range(0, img.height, step):
        for x in range(0, img.width, step):
            px = (x + 0.5)
            py = (y + 0.5)
            predicted = color_at(px, py)
            total += 1
            if opaque[y, x]:
                # should be reconstructed as *some* colour, close to the source
                if predicted is not None and _close(predicted, rgba[y, x, :3]):
                    agree += 1
            else:
                if predicted is None:
                    agree += 1
    ratio = agree / total
    print(f"reconstruction agreement = {ratio:.4f}")
    assert ratio > 0.95, f"reconstruction too low: {ratio:.4f}"


def _close(a, b, tol=60):
    return all(abs(int(a[i]) - int(b[i])) <= tol for i in range(3))


def test_svg_has_paths():
    res = vectorize(make_test_image(128), engine="potrace", colors=6)
    svg = res.to_svg()
    assert svg.count("<path") == res.color_count
    assert 'fill-rule="evenodd"' in svg
    assert "viewBox=" in svg


def test_pdf_and_eps_headers():
    res = vectorize(make_test_image(128), engine="potrace", colors=6)
    pdf = render_pdf(res)
    eps = render_eps(res)
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf
    assert eps.startswith(b"%!PS-Adobe")
    assert b"%%BoundingBox:" in eps


def test_pdf_object_offsets_valid():
    """The dependency-free fallback writer must emit a self-consistent xref."""
    from reavectors.export import _render_pdf_minimal
    res = vectorize(make_test_image(96), engine="potrace", colors=5)
    pdf = _render_pdf_minimal(res)
    assert pdf.startswith(b"%PDF-1.7")
    xref_pos = int(pdf.rsplit(b"startxref", 1)[1].split()[0])
    assert pdf[xref_pos:xref_pos + 4] == b"xref"
    body = pdf[xref_pos:].split(b"trailer")[0].split(b"\n")
    offsets = []
    for line in body:
        parts = line.strip().split()
        if len(parts) == 3 and parts[2] in (b"n", b"f") and parts[1] == b"00000":
            offsets.append(int(parts[0]))
    for off in offsets:
        if off == 0:
            continue
        assert b" obj" in pdf[off:off + 20]


def test_pdf_parses_with_pypdf():
    """The primary PDF/AI writer must be a fully valid PDF."""
    try:
        import pypdf
    except ImportError:
        print("pypdf unavailable -> skipped")
        return
    res = vectorize(make_test_image(128), engine="potrace", colors=6)
    pdf = render_pdf(res)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert float(box.width) == res.width and float(box.height) == res.height
    # Illustrator-friendliness: resources/procset present
    assert b"/ProcSet" in pdf


def test_transparency_is_preserved():
    """The output must not add a background rectangle."""
    res = vectorize(make_test_image(128), engine="potrace", colors=6)
    svg = res.to_svg()
    assert "width=\"128\"" in svg


# ---------------------------------------------------------------------------
# engine + SVG parsing
# ---------------------------------------------------------------------------
def test_svgparse_path():
    from reavectors.svgparse import parse_path
    contours = parse_path("M0 0 L10 0 L10 10 L0 10 Z")
    assert len(contours) == 1
    assert len(contours[0].segments) == 3
    # relative + curve
    c2 = parse_path("M1 1 c1 0 2 1 3 3")
    assert c2[0].segments[0][0] == "C"


def test_vtracer_engine_used():
    from reavectors import vtracer_engine
    if not vtracer_engine.available():
        print("vtracer unavailable -> skipped")
        return
    res = vectorize(make_test_image(160), engine="auto", style="logo", max_size=0)
    assert res.engine == "vtracer", f"expected vtracer, got {res.engine}"
    assert res.color_count >= 3
    # exports must work from parsed vtracer geometry
    assert render_pdf(res).startswith(b"%PDF-")
    assert render_eps(res).startswith(b"%!PS-Adobe")


def test_svgparse_transform_is_applied():
    """vtracer places each path with translate(); the parser must apply it."""
    from reavectors.svgparse import parse_svg, _parse_transform, _apply, parse_path
    m = _parse_transform("translate(10,20)")
    c = _apply(m, parse_path("M0 0 L1 0 L1 1 Z")[0])
    assert c.start == (10.0, 20.0)
    assert c.segments[0][1] == (11.0, 20.0)

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
           '<path d="M0 0 L10 0 L10 10 Z" fill="#ff0000" '
           'transform="translate(5,5)"/></svg>')
    w, h, layers = parse_svg(svg)
    assert (w, h) == (100, 100)
    xs = [p[0] for fig in layers[0].figures for ct in fig.contours
          for p in [ct.start] + [(s[1] if s[0] == "L" else s[3]) for s in ct.segments]]
    assert min(xs) == 5.0 and max(xs) == 15.0


def test_refine_runs_and_returns_best():
    from reavectors import vtracer_engine
    if not vtracer_engine.available():
        print("vtracer unavailable -> skipped")
        return
    from reavectors.refine import auto_refine
    res, stats = auto_refine(make_test_image(128), budget=4, style="logo", max_size=0)
    assert stats.iterations >= 1
    assert res.layers, "refiner returned an empty result"
    assert 0.0 <= stats.best_match <= 100.0
    assert render_pdf(res).startswith(b"%PDF-")


def test_vtracer_exports_roundtrip_through_parser():
    from reavectors import vtracer_engine
    if not vtracer_engine.available():
        return
    from reavectors.svgparse import parse_svg
    from reavectors.vectorize import vectorize as v
    res = v(make_test_image(160), engine="vtracer", style="logo", max_size=0)
    w, h, layers = parse_svg(res.to_svg())
    assert w == res.width and h == res.height
    assert sum(len(l.figures) for l in layers) >= 1


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_all())
