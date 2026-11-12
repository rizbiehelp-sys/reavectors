"""
reavectors.export
=================

Serialise a :class:`~reavectors.vectorize.VectorResult` to formats that open in
vector editors:

* ``render_pdf``  -> PDF bytes. Adobe Illustrator opens PDF natively; this is
  the same "PDF-compatible" trick real ``.ai`` files use, so it is written out
  with an ``.ai`` extension when the user asks for AI.
* ``render_eps``  -> Encapsulated PostScript bytes (Illustrator/Inkscape open
  these and can save them as ``.ai`` or ``.svg``).

Both writers emit pure vector paths with **no background rectangle**, so
transparency is preserved.
"""

from __future__ import annotations

from typing import List

from .vectorize import Contour, VectorResult


def _num(v, precision=3) -> str:
    s = f"{float(v):.{precision}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


# ---------------------------------------------------------------------------
# EPS / PostScript  (coordinate system is y-up, origin bottom-left)
# ---------------------------------------------------------------------------

def render_eps(result: VectorResult, precision: int = 3) -> bytes:
    """Return Encapsulated PostScript for the document."""
    W, H = result.width, result.height
    n = lambda v: _num(v, precision)
    fill_op = "fill" if result.fill_rule == "nonzero" else "eofill"

    lines: List[str] = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: 0 0 {W} {H}",
        f"%%HiResBoundingBox: 0 0 {W} {H}",
        "%%Creator: reavectors",
        "%%Title: reavectors output",
        "%%LanguageLevel: 2",
        "%%EndComments",
        "gsave 1 setlinejoin 1 setlinecap",
    ]

    for layer in result.layers:
        if not layer.figures:
            continue
        r, g, b = (c / 255.0 for c in layer.color)
        lines.append(f"{n(r)} {n(g)} {n(b)} setrgbcolor")
        lines.append("newpath")
        for fig in layer.figures:
            for contour in fig.contours:
                lines.append(_contour_ps(contour, H, n))
        lines.append(fill_op)

    lines += ["grestore", "showpage", "%%EOF"]
    return ("\n".join(lines) + "\n").encode("latin-1", "replace")


def _contour_ps(contour: Contour, height: int, n) -> str:
    x, y = contour.start
    parts = [f"{n(x)} {n(height - y)} moveto"]
    for seg in contour.segments:
        if seg[0] == "L":
            ex, ey = seg[1]
            parts.append(f"{n(ex)} {n(height - ey)} lineto")
        else:
            _, c1, c2, e = seg
            parts.append(
                f"{n(c1[0])} {n(height - c1[1])} "
                f"{n(c2[0])} {n(height - c2[1])} "
                f"{n(e[0])} {n(height - e[1])} curveto"
            )
    parts.append("closepath")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# PDF  (coordinate system is y-up, origin bottom-left; built by hand, no deps)
# ---------------------------------------------------------------------------

def render_pdf(result: VectorResult, precision: int = 3) -> bytes:
    """
    Return a single-page PDF (also written out with a ``.ai`` extension).

    Prefers **ReportLab**, which emits a fully-formed PDF -- correct
    ``/Resources``, ``/ProcSet``, ``/Group`` and metadata -- that Adobe
    Illustrator opens reliably. A minimal built-in writer (``_render_pdf_minimal``)
    is used only if ReportLab is not installed.
    """
    try:
        import io
        from reportlab.pdfgen import canvas
        from reportlab.pdfgen.canvas import FILL_EVEN_ODD, FILL_NON_ZERO
    except Exception:  # noqa: BLE001 - ReportLab optional
        return _render_pdf_minimal(result, precision)

    W = max(1, int(result.width))
    H = max(1, int(result.height))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle("reavectors output")
    c.setAuthor("reavectors")
    c.setSubject("Vector artwork traced with reavectors")
    c.setCreator("reavectors")
    c.setProducer("reavectors")

    fillmode = FILL_NON_ZERO if result.fill_rule == "nonzero" else FILL_EVEN_ODD

    for layer in result.layers:
        if not layer.figures:
            continue
        r, g, b = (v / 255.0 for v in layer.color)
        c.setFillColorRGB(r, g, b)
        path = c.beginPath()
        for fig in layer.figures:
            for contour in fig.contours:
                x, y = contour.start
                path.moveTo(x, H - y)
                for seg in contour.segments:
                    if seg[0] == "L":
                        path.lineTo(seg[1][0], H - seg[1][1])
                    else:
                        _, c1, c2, e = seg
                        path.curveTo(c1[0], H - c1[1], c2[0], H - c2[1], e[0], H - e[1])
                path.close()
        c.drawPath(path, stroke=0, fill=1, fillMode=fillmode)

    c.showPage()
    c.save()
    return buf.getvalue()


def _render_pdf_minimal(result: VectorResult, precision: int = 3) -> bytes:
    """Dependency-free fallback PDF writer (used only without ReportLab)."""
    W, H = result.width, result.height
    n = lambda v: _num(v, precision)
    fill_op = "f" if result.fill_rule == "nonzero" else "f*"

    ops: List[str] = []
    for layer in result.layers:
        if not layer.figures:
            continue
        r, g, b = (c / 255.0 for c in layer.color)
        ops.append(f"{n(r)} {n(g)} {n(b)} rg")
        for fig in layer.figures:
            for contour in fig.contours:
                ops.append(_contour_pdf(contour, H, n))
        ops.append(fill_op)  # nonzero (vtracer) or even-odd (potrace) fill
    content = ("\n".join(ops) + "\n").encode("latin-1", "replace")

    objects: List[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
         f"/Contents 4 0 R /Resources << >> >>").encode("latin-1"),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
    ]
    return _assemble_pdf(objects)


def _contour_pdf(contour: Contour, height: int, n) -> str:
    x, y = contour.start
    parts = [f"{n(x)} {n(height - y)} m"]
    for seg in contour.segments:
        if seg[0] == "L":
            ex, ey = seg[1]
            parts.append(f"{n(ex)} {n(height - ey)} l")
        else:
            _, c1, c2, e = seg
            parts.append(
                f"{n(c1[0])} {n(height - c1[1])} "
                f"{n(c2[0])} {n(height - c2[1])} "
                f"{n(e[0])} {n(height - e[1])} c"
            )
    parts.append("h")
    return " ".join(parts)


def _assemble_pdf(objects: List[bytes]) -> bytes:
    """Assemble a minimal PDF from a list of object bodies (1-indexed)."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1")
        out += body
        out += b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {n} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode("latin-1")
    return bytes(out)
