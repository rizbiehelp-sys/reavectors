"""
reavectors
==========

An original, offline transparent-PNG -> vector converter (SVG / AI / PDF / EPS).

Public API::

    from reavectors import vectorize, render_pdf, render_eps
    result = vectorize("logo.png", colors=8)
    open("logo.svg", "w").write(result.to_svg())
    open("logo.ai", "wb").write(render_pdf(result))
"""

from .vectorize import (
    VectorResult,
    Layer,
    Figure,
    Contour,
    vectorize,
)
from .export import render_pdf, render_eps

__all__ = [
    "VectorResult",
    "Layer",
    "Figure",
    "Contour",
    "vectorize",
    "render_pdf",
    "render_eps",
]

__version__ = "0.1.0"
