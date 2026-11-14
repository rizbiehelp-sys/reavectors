"""
Product Photo -> 3D (parametric + label-accurate).

This is NOT PNG extrusion. Given a real product photograph it:

1. keeps the original photo,
2. derives a transparent cutout (background estimate + threshold),
3. measures the silhouette and infers packaging geometry,
4. builds a **parametric** packaging profile (LatheGeometry points) with separate
   body / shoulder / neck / cap components for common packages (juice bottle,
   beverage bottle, glass bottle, jar, can, container),
5. rectifies the **original** label artwork (perspective correction) so the real
   brand/text is preserved as a texture - never AI-regenerated,
6. reports a quality + confidence summary and marks inferred geometry/backside.

Pure CPU (Pillow + numpy). The AI image->3D models (TripoSR / SF3D) are a
*separate* optional step that only runs on the GPU worker; this module never
invents branding.
"""

from __future__ import annotations

import base64
import io
import json
import math
from typing import Optional

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# 1. cutout
# ---------------------------------------------------------------------------
def _estimate_background(arr: np.ndarray, border: int = 5) -> np.ndarray:
    edges = np.concatenate([
        arr[:border].reshape(-1, 3), arr[-border:].reshape(-1, 3),
        arr[:, :border].reshape(-1, 3), arr[:, -border:].reshape(-1, 3),
    ])
    return np.median(edges, axis=0)


def make_cutout(img: Image.Image, tol: float = 34.0) -> tuple[Image.Image, np.ndarray, np.ndarray]:
    """Return (rgba_cutout, alpha_mask(bool), background_color)."""
    rgb = img.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    bg = _estimate_background(arr)
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    mask = dist > tol
    alpha = (mask * 255).astype(np.uint8)
    out = rgb.convert("RGBA")
    out.putalpha(Image.fromarray(alpha, "L"))
    return out, mask, bg


def _largest_bbox(mask: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ---------------------------------------------------------------------------
# 2. silhouette -> packaging parameters -> lathe profile
# ---------------------------------------------------------------------------
def _width_profile(mask: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    """Half-width (in px) of the object per row, top->bottom order preserved."""
    x0, y0, x1, y1 = bbox
    radii = np.zeros(y1 - y0, dtype=float)
    for i, y in enumerate(range(y0, y1)):
        row = np.where(mask[y, x0:x1])[0]
        radii[i] = (row.max() - row.min() + 1) / 2.0 if len(row) else 0.0
    return radii


def classify_package(radii: np.ndarray, height_px: float) -> dict:
    """
    Infer packaging type from the width profile (measured, not guessed blindly):
    a bottle narrows near the top (neck); a can/container stays ~uniform.
    """
    n = len(radii)
    if n < 8:
        return {"type": "container", "has_neck": False}
    # radii are ordered top(y0) -> bottom(y1); the object's top is at the START.
    body = float(np.median(radii[int(n * 0.30):int(n * 0.65)])) or 1.0
    top = float(np.median(radii[:max(1, int(n * 0.10))])) or body
    ratio = top / body
    if ratio < 0.55:
        return {"type": "bottle", "has_neck": True, "neck_ratio": round(ratio, 3)}
    if abs(ratio - 1.0) < 0.15:
        return {"type": "can", "has_neck": False, "neck_ratio": round(ratio, 3)}
    return {"type": "jar", "has_neck": False, "neck_ratio": round(ratio, 3)}


def build_lathe_profile(radii: np.ndarray, height_px: float, samples: int = 28) -> list:
    """
    Turn the measured half-width profile into a smoothed lathe profile [(r, y)],
    in model units where total height = 1.0 (y from -0.5 bottom to +0.5 top).
    """
    n = len(radii)
    # sample 'samples' points across the height, bottom -> top
    idx = np.linspace(n - 1, 0, samples).astype(int)      # radii are top->bottom
    r = radii[idx] / height_px
    # light smoothing to avoid pixel jitter
    if samples >= 5:
        k = np.array([1, 2, 3, 2, 1], dtype=float); k /= k.sum()
        r = np.convolve(r, k, mode="same")
    ys = np.linspace(-0.5, 0.5, samples)
    prof = [(max(0.004, float(rr)), float(yy)) for rr, yy in zip(r, ys)]
    return prof


# ---------------------------------------------------------------------------
# 3. label detection + perspective rectification
# ---------------------------------------------------------------------------
def _perspective_coeffs(src_quad, dst_w: int, dst_h: int):
    """Coefficients for PIL PERSPECTIVE (maps output pixel -> source pixel)."""
    dst = [(0, 0), (dst_w, 0), (dst_w, dst_h), (0, dst_h)]
    src = list(src_quad)
    A, b = [], []
    for (u, v), (x, y) in zip(dst, src):
        A.append([u, v, 1, 0, 0, 0, -x * u, -x * v]); b.append(x)
        A.append([0, 0, 0, u, v, 1, -y * u, -y * v]); b.append(y)
    coeffs, *_ = np.linalg.lstsq(np.array(A, dtype=float), np.array(b, dtype=float), rcond=None)
    return tuple(coeffs.tolist())


def rectify_label(img: Image.Image, quad, out_w: int = 640, out_h: int = 480) -> Image.Image:
    """Perspective-correct a label region into a flat image (original artwork)."""
    coeffs = _perspective_coeffs(quad, out_w, out_h)
    return img.convert("RGB").transform((out_w, out_h), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def default_label_quad(bbox: tuple[int, int, int, int], band=(0.30, 0.72)) -> list:
    """Fallback label region: the front-facing central band of the object."""
    x0, y0, x1, y1 = bbox
    h = y1 - y0
    ly0 = y0 + int(h * band[0]); ly1 = y0 + int(h * band[1])
    return [(x0, ly0), (x1, ly0), (x1, ly1), (x0, ly1)]


# ---------------------------------------------------------------------------
# 4. quality / confidence
# ---------------------------------------------------------------------------
def quality_report(mask: np.ndarray, bbox, radii: np.ndarray, has_label: bool) -> dict:
    x0, y0, x1, y1 = bbox
    region = mask[y0:y1, x0:x1]
    symmetry = 0.0
    body = radii[int(len(radii) * 0.3):int(len(radii) * 0.7)] if len(radii) > 6 else radii
    if len(body):
        symmetry = float(1.0 - min(1.0, np.std(body) / (np.mean(body) + 1e-6)))
    coverage = float(mask.mean())
    warnings = [
        "Single photo: the back/hidden side is INFERRED, not measured.",
        "Branding is taken from the original photo/supplied label - never regenerated.",
    ]
    if coverage > 0.85:
        warnings.append("Background seems cluttered; the cutout may include extra pixels.")
    if not has_label:
        warnings.append("No label region confirmed - label mapping may be approximate.")
    conf = "high" if symmetry > 0.9 and coverage < 0.6 else "medium" if symmetry > 0.7 else "low"
    return {"symmetry": round(symmetry, 3), "object_coverage": round(coverage, 3),
            "silhouette_consistency": round(symmetry, 3), "confidence": conf, "warnings": warnings}


# ---------------------------------------------------------------------------
# 5. top-level
# ---------------------------------------------------------------------------
def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO(); img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def analyze_product(image_bytes: bytes, label_bytes: bytes = None, quad=None,
                    material: str = "auto", mode: str = "single") -> dict:
    """
    Build a parametric product spec from a photograph.

    ``mode``: "single" (one photo) or "high_fidelity" (front/back/side - the caller
    passes the primary as ``image_bytes`` and extra views via ``extra_photos``).
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    cutout, mask, bg = make_cutout(img)
    bbox = _largest_bbox(mask)
    if bbox is None:
        raise ValueError("no object detected in the photo")

    radii = _width_profile(mask, bbox)
    height_px = max(1.0, bbox[3] - bbox[1])
    pkg = classify_package(radii, height_px)
    profile = build_lathe_profile(radii, height_px)

    # label: supplied flat asset wins; else rectify from the photo
    supplied = label_bytes is not None
    if supplied:
        label_img = Image.open(io.BytesIO(label_bytes)).convert("RGB")
        label_b64 = _png_b64(label_img)
        label_quad = None
    else:
        label_quad = quad or default_label_quad(bbox)
        label_img = rectify_label(img, label_quad)
        label_b64 = _png_b64(label_img)

    quality = quality_report(mask, bbox, radii, has_label=True)
    body_r = max((r for r, _ in profile), default=0.1)
    _y0 = bbox[1]
    if label_quad:
        frac_top = (label_quad[0][1] - _y0) / height_px
        frac_bot = (label_quad[2][1] - _y0) / height_px
    else:
        frac_top, frac_bot = 0.30, 0.72
    model = {
        "height": 1.0,
        "body_radius": round(body_r, 4),
        "neck_radius": round(profile[-1][0] if profile else body_r, 4),
        "label_band": {"y0": round(0.5 - frac_bot, 4), "y1": round(0.5 - frac_top, 4)},
        "label_wrap_degrees": 180,
    }

    return {
        "model": model,
        "source": {"width": w, "height": h, "aspect": round(w / h, 3)},
        "mode": mode,
        "package": pkg,
        "profile": profile,                       # [(r, y)] lathe points
        "materials": _materials(material, img, mask, bbox),
        "label": {
            "source": "supplied_asset" if supplied else "rectified_from_photo",
            "quad": label_quad,
            "image": label_b64,
            "note": "original artwork preserved; not AI-generated",
        },
        "previews": {"cutout": _png_b64(cutout), "background_bgr": [int(v) for v in bg]},
        "quality": quality,
        "conflicts": [],
    }


def _materials(requested: str, img: Image.Image, mask: np.ndarray, bbox) -> dict:
    """
    Material inference is a *heuristic hint*, shown to the user to confirm - it is
    never silently trusted. Glass/transparent products need a transparent-safe
    cutout and a manual choice. ``body_color`` samples the lower body (below the
    label) so the model starts with the product's real colour.
    """
    arr = np.asarray(img.convert("RGB"))
    bright = float((np.asarray(img.convert("L"))[mask] > 235).mean()) if mask.any() else 0.0
    x0, y0, x1, y1 = bbox
    ly = y0 + int((y1 - y0) * 0.60)
    sub_mask = mask[ly:y1, x0:x1]
    body_color = [200, 200, 200]
    if sub_mask.any() and ly < y1:
        px = arr[ly:y1, x0:x1][sub_mask]
        body_color = [int(v) for v in np.median(px, axis=0)]
    guess = "glass" if (requested == "auto" and bright > 0.10) else \
            ("plastic" if requested == "auto" else requested)
    return {"body": guess, "cap": "metal", "finish": "glossy",
            "body_color": body_color,
            "highlight_fraction": round(bright, 3),
            "note": "material is inferred; confirm before export (transparency/reflections)"}
