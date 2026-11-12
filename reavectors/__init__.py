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

import os as _os

# Pin BLAS/OpenMP to a single thread *before* numpy is imported. Our workload
# (small images) gains nothing from a thread pool, and on memory-constrained
# hosts OpenBLAS otherwise tries to allocate large per-thread buffers and can
# fail with "Memory allocation still failed after 10 retries".
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    _os.environ.setdefault(_var, "1")

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

__version__ = "0.3.0"
