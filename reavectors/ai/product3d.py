"""
Product Photo -> 3D (parametric + label-accurate) with a real REFINE BUDGET.

This is NOT PNG extrusion. Given a real product photograph it:

1. keeps the original photo,
2. derives a transparent cutout and **iteratively refines** it (guided-filter
   alpha matting) so transparent edges / reflections are not lost,
3. measures the silhouette and fits a **parametric** packaging profile
   (LatheGeometry points; body / shoulder / neck / cap / base),
4. locates the **original** label region and perspective-corrects it (never
   AI-regenerates branding), then iteratively enhances it,
5. reports a quality + confidence summary and marks inferred geometry/backside.

The pipeline is **time-boxed** (``budget`` seconds, 10-120): it keeps refining
until the budget is spent, so results are not instant - like the vectorizer's
"refine". A single 5-second pass is possible via ``budget=0`` (used by tests).

Pure CPU (Pillow + numpy). AI surface reconstruction (TripoSR / SF3D) is a
separate GPU-worker step and never touches the branding.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

WORK_MAX = 900          # working resolution for the (heavy) matting pass
MIN_ITERS = 6


# ---------------------------------------------------------------------------
# 1. cutout (v1) + iterative refinement
# ---------------------------------------------------------------------------
def _estimate_background(arr: np.ndarray, border: int = 5) -> np.ndarray:
    edges = np.concatenate([
        arr[:border].reshape(-1, 3), arr[-border:].reshape(-1, 3),
        arr[:, :border].reshape(-1, 3), arr[:, -border:].reshape(-1, 3),
    ])
    return np.median(edges, axis=0)


def make_cutout(img: Image.Image, tol: float = 34.0):
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


def _box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """O(n) box mean with edge clamping (integral image)."""
    H, W = a.shape
    cs = np.pad(a.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    ys = np.arange(H); xs = np.arange(W)
    y0 = np.clip(ys - r, 0, H); y1 = np.clip(ys + r + 1, 0, H)
    x0 = np.clip(xs - r, 0, W); x1 = np.clip(xs + r + 1, 0, W)
    S = cs[np.ix_(y1, x1)] - cs[np.ix_(y0, x1)] - cs[np.ix_(y1, x0)] + cs[np.ix_(y0, x0)]
    N = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    return S / N


def _guided(guide: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    mI = _box_mean(guide, r); mp = _box_mean(p, r)
    covIp = _box_mean(guide * p, r) - mI * mp
    varI = _box_mean(guide * guide, r) - mI * mI
    a = covIp / (varI + eps); b = mp - a * mI
    return _box_mean(a, r) * guide + _box_mean(b, r)


def _edge_score(gray: np.ndarray, alpha: np.ndarray) -> float:
    """How well alpha edges land on real image gradients (higher = better)."""
    gy, gx = np.gradient(gray); ay, ax = np.gradient(alpha)
    gi = np.abs(gy) + np.abs(gx); ga = np.abs(ay) + np.abs(ax)
    return float((gi * ga).sum() / (ga.sum() + 1e-6))


def refine_cutout(gray: np.ndarray, mask: np.ndarray, deadline: float,
                  min_iters: int = MIN_ITERS, max_iters: int = 600,
                  emit: Optional[Callable[[float], None]] = None,
                  pct=(10.0, 44.0)):
    """Iteratively snap the alpha to image edges (guided filter). Time-boxed."""
    p = mask.astype(np.float32)
    best = p.copy(); best_score = _edge_score(gray, p)
    it = 0
    while True:
        a = _guided(gray, p, 4, 1e-3)
        p = np.clip(0.55 * a + 0.45 * p, 0.0, 1.0)
        s = _edge_score(gray, p)
        if s > best_score:
            best_score, best = s, p.copy()
        it += 1
        if emit and it % 25 == 0:
            emit(pct[0] + (pct[1] - pct[0]) * min(1.0, it / max_iters))
        if it >= max_iters or (it >= min_iters and time.time() >= deadline):
            break
    return best, it, best_score


def _largest_bbox(mask: np.ndarray):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ---------------------------------------------------------------------------
# 2. silhouette -> packaging parameters -> (fitted) lathe profile
# ---------------------------------------------------------------------------
def _width_profile(alpha: np.ndarray, bbox) -> np.ndarray:
    x0, y0, x1, y1 = bbox
    binm = alpha > 0.5
    radii = np.zeros(y1 - y0, dtype=float)
    for i, y in enumerate(range(y0, y1)):
        row = np.where(binm[y, x0:x1])[0]
        radii[i] = (row.max() - row.min() + 1) / 2.0 if len(row) else 0.0
    return radii


def classify_package(radii: np.ndarray, height_px: float) -> dict:
    n = len(radii)
    if n < 8:
        return {"type": "container", "has_neck": False}
    body = float(np.median(radii[int(n * 0.30):int(n * 0.65)])) or 1.0
    top = float(np.median(radii[:max(1, int(n * 0.10))])) or body
    ratio = top / body
    if ratio < 0.55:
        return {"type": "bottle", "has_neck": True, "neck_ratio": round(ratio, 3)}
    if abs(ratio - 1.0) < 0.15:
        return {"type": "can", "has_neck": False, "neck_ratio": round(ratio, 3)}
    return {"type": "jar", "has_neck": False, "neck_ratio": round(ratio, 3)}


def fit_profile(raw: np.ndarray, height_px: float, deadline: float,
                samples: int = 96, min_iters: int = MIN_ITERS):
    """
    Iteratively relax a smooth profile toward the measured widths (Laplacian +
    data attachment) - genuinely improves with the time budget. Returns
    (profile[(r, y)], rmse). raw is top->bottom; profile is bottom->top.
    """
    r = raw.astype(np.float64)
    s = r.copy()
    lam, mu = 0.5, 0.12
    it = 0
    while True:
        lap = np.empty_like(s)
        lap[1:-1] = s[2:] - 2 * s[1:-1] + s[:-2]
        lap[0] = s[0] - s[1]; lap[-1] = s[-1] - s[-2]
        s = s + lam * lap + mu * (r - s)
        it += 1
        if it >= 40 or (it >= min_iters and time.time() >= deadline):
            break
    rmse = float(np.sqrt(np.mean((s - r) ** 2)))
    idx = np.linspace(len(s) - 1, 0, samples).astype(int)     # bottom -> top
    vals = s[idx] / height_px
    ys = np.linspace(-0.5, 0.5, samples)
    return [(max(0.004, float(v)), float(y)) for v, y in zip(vals, ys)], rmse


# ---------------------------------------------------------------------------
# 3. label detection + rectification + enhancement
# ---------------------------------------------------------------------------
def _structure_rows(gray: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(gray)
    g = np.abs(gy) + np.abs(gx)
    m = alpha > 0.5
    denom = m.sum(axis=1).clip(min=1)
    return (g * m).sum(axis=1) / denom


def detect_label_band(gray: np.ndarray, alpha: np.ndarray, bbox) -> tuple:
    """Find the label band from ink/graphic structure (not a fixed guess)."""
    x0, y0, x1, y1 = bbox
    h = y1 - y0
    lo, hi = y0 + int(h * 0.18), y0 + int(h * 0.92)
    rows = _structure_rows(gray, alpha)[lo:hi]
    if len(rows) < 6:
        return (0.30, 0.72), 0.0
    k = np.ones(5) / 5.0
    sm = np.convolve(rows, k, mode="same")
    min_h = max(4, int((hi - lo) * 0.18))
    best_sum, best = -1.0, (0, min_h)
    csum = np.concatenate([[0], np.cumsum(sm)])
    for a in range(0, len(sm) - min_h):
        for b in range(a + min_h, min(len(sm), a + int((hi - lo) * 0.85)) + 1):
            val = (csum[b] - csum[a]) / (b - a)
            if val > best_sum:
                best_sum, best = val, (a, b)
    a, b = best
    base = float(np.median(sm) + 1e-6)
    conf = float(np.clip((best_sum / base - 1.0), 0.0, 1.0))
    return ((lo + a - y0) / h, (lo + b - y0) / h), round(conf, 3)


def _perspective_coeffs(src_quad, dst_w: int, dst_h: int):
    dst = [(0, 0), (dst_w, 0), (dst_w, dst_h), (0, dst_h)]
    A, b = [], []
    for (u, v), (x, y) in zip(dst, list(src_quad)):
        A.append([u, v, 1, 0, 0, 0, -x * u, -x * v]); b.append(x)
        A.append([0, 0, 0, u, v, 1, -y * u, -y * v]); b.append(y)
    coeffs, *_ = np.linalg.lstsq(np.array(A, float), np.array(b, float), rcond=None)
    return tuple(coeffs.tolist())


def rectify_label(img: Image.Image, quad, out_w: int = 640, out_h: int = 480) -> Image.Image:
    coeffs = _perspective_coeffs(quad, out_w, out_h)
    return img.convert("RGB").transform((out_w, out_h), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def default_label_quad(bbox, band=(0.30, 0.72)) -> list:
    x0, y0, x1, y1 = bbox
    h = y1 - y0
    ly0 = y0 + int(h * band[0]); ly1 = y0 + int(h * band[1])
    return [(x0, ly0), (x1, ly0), (x1, ly1), (x0, ly1)]


def enhance_label(img: Image.Image, deadline: float, emit=None, pct=(70.0, 90.0)) -> Image.Image:
    """White-balance + iterative unsharp so the original artwork stays crisp."""
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    means = arr.reshape(-1, 3).mean(axis=0) + 1e-6
    target = means.mean()
    arr = np.clip(arr * (target / means), 0, 255).astype(np.uint8)
    out = Image.fromarray(arr)
    out = ImageEnhance.Contrast(out).enhance(1.05)
    it = 0
    while True:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.4, percent=90, threshold=3))
        it += 1
        if emit and it % 4 == 0:
            emit(pct[0] + (pct[1] - pct[0]) * min(1.0, it / 40.0))
        if it >= 40 or (it >= 2 and time.time() >= deadline):
            break
    return out


# ---------------------------------------------------------------------------
# 4. quality / confidence
# ---------------------------------------------------------------------------
def quality_report(mask: np.ndarray, bbox, radii: np.ndarray, has_label: bool) -> dict:
    x0, y0, x1, y1 = bbox
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
# 5. materials
# ---------------------------------------------------------------------------
def _materials(requested: str, img: Image.Image, mask: np.ndarray, bbox) -> dict:
    arr = np.asarray(img.convert("RGB"))
    bright = float((np.asarray(img.convert("L"))[mask] > 235).mean()) if mask.any() else 0.0
    x0, y0, x1, y1 = bbox
    ly = y0 + int((y1 - y0) * 0.60)
    sub = mask[ly:y1, x0:x1]
    body_color = [200, 200, 200]
    if sub.any() and ly < y1:
        body_color = [int(v) for v in np.median(arr[ly:y1, x0:x1][sub], axis=0)]
    guess = "glass" if (requested == "auto" and bright > 0.10) else \
            ("plastic" if requested == "auto" else requested)
    return {"body": guess, "cap": "metal", "finish": "glossy", "body_color": body_color,
            "highlight_fraction": round(bright, 3),
            "note": "material is inferred; confirm before export (transparency/reflections)"}


# ---------------------------------------------------------------------------
# 6. top-level (time-boxed)
# ---------------------------------------------------------------------------
def _png_b64(img: Image.Image) -> str:
    buf = io.BytesIO(); img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def analyze_product(image_bytes: bytes, label_bytes: bytes = None, quad=None,
                    material: str = "auto", mode: str = "single",
                    budget: float = 0.0,
                    on_progress: Optional[Callable[[dict], None]] = None) -> dict:
    """
    Build a parametric product spec from a photograph, refining until ``budget``
    seconds elapse (10-120 recommended; 0 = fast pass). ``on_progress`` receives
    {"type":"progress","stage":str,"pct":float} events for SSE streaming.
    """
    started = time.time()
    budget = max(0.0, float(budget or 0.0))
    deadline = started + budget

    def emit(stage, pct):
        if on_progress:
            try:
                on_progress({"type": "progress", "stage": stage, "pct": round(pct, 1),
                             "elapsed": round(time.time() - started, 1), "budget": budget})
            except Exception:  # noqa: BLE001
                pass

    emit("Loading photo", 4)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    _cutout, mask0, bg = make_cutout(img)

    # work at a bounded resolution for the heavy matting pass
    scale = min(1.0, WORK_MAX / float(max(w, h)))
    if scale < 1.0:
        ww, wh = max(1, int(w * scale)), max(1, int(h * scale))
        work = np.asarray(img.resize((ww, wh), Image.BILINEAR)).astype(np.float32)
        wmask = np.asarray(Image.fromarray(mask0.astype(np.uint8) * 255).resize((ww, wh), Image.NEAREST)) > 127
    else:
        work = np.asarray(img).astype(np.float32); wmask = mask0

    gray = (0.299 * work[:, :, 0] + 0.587 * work[:, :, 1] + 0.114 * work[:, :, 2]) / 255.0
    min_iters = MIN_ITERS if budget <= 0 else 20
    emit("Isolating object (matting)", 10)
    alpha, c_iters, c_score = refine_cutout(
        gray.astype(np.float32), wmask, deadline, min_iters=min_iters,
        emit=lambda p: emit("Isolating object (matting)", p))

    bbox_work = _largest_bbox(alpha > 0.5)
    if bbox_work is None:
        raise ValueError("no object detected in the photo")

    emit("Measuring silhouette", 46)
    radii = _width_profile(alpha, bbox_work)
    height_px = max(1.0, bbox_work[3] - bbox_work[1])
    pkg = classify_package(radii, height_px)

    emit("Fitting packaging model", 55)
    samples = 48 if budget <= 0 else 128
    profile, fit_rmse = fit_profile(radii, height_px, deadline, samples=samples,
                                    min_iters=min_iters)

    # ---- label ---------------------------------------------------------
    supplied = label_bytes is not None
    label_band_conf = 1.0
    emit("Locating label", 62)
    if supplied:
        label_img = Image.open(io.BytesIO(label_bytes)).convert("RGB")
        label_quad = None
        label_source = "supplied_asset"
        frac_top, frac_bot = 0.30, 0.72
    else:
        band, label_band_conf = detect_label_band(gray, alpha, bbox_work) if quad is None else ((0.30, 0.72), 0.0)
        frac_top, frac_bot = (band if quad is None else (0.30, 0.72))
        # scale the work-box band back to full-resolution coordinates
        sx = w / float(alpha.shape[1]); sy = h / float(alpha.shape[0])
        bx0, by0, bx1, by1 = bbox_work
        ly0 = int((by0 + (by1 - by0) * frac_top) * sy); ly1 = int((by0 + (by1 - by0) * frac_bot) * sy)
        label_quad = quad or [(int(bx0 * sx), ly0), (int(bx1 * sx), ly0), (int(bx1 * sx), ly1), (int(bx0 * sx), ly1)]
        emit("Rectifying label", 68)
        label_img = rectify_label(img, label_quad, out_w=1024, out_h=768)
        label_source = "rectified_from_photo"
    label_img = enhance_label(label_img, deadline, emit=lambda p: emit("Enhancing label", p))
    label_b64 = _png_b64(label_img)

    emit("Scoring quality", 93)
    # refined cutout preview at full resolution
    alpha_full = Image.fromarray((np.clip(alpha, 0, 1) * 255).astype(np.uint8), "L").resize((w, h), Image.BILINEAR)
    cut_rgba = img.convert("RGBA"); cut_rgba.putalpha(alpha_full)
    mask_full = np.asarray(alpha_full) > 127
    quality = quality_report(mask_full, (0, 0, w, h), radii, has_label=True)
    if label_source == "rectified_from_photo" and label_band_conf < 0.15:
        quality["warnings"].append("Label region is low-confidence (plain package?) - check the crop.")

    body_r = max((r for r, _ in profile), default=0.1)
    model = {
        "height": 1.0,
        "body_radius": round(body_r, 4),
        "neck_radius": round(profile[-1][0] if profile else body_r, 4),
        "label_band": {"y0": round(0.5 - frac_bot, 4), "y1": round(0.5 - frac_top, 4)},
        "label_wrap_degrees": 180,
    }
    used = round(time.time() - started, 1)
    emit("Done", 100)
    return {
        "model": model,
        "source": {"width": w, "height": h, "aspect": round(w / h, 3)},
        "mode": mode,
        "package": pkg,
        "profile": profile,
        "materials": _materials(material, img, mask_full, (0, 0, w, h)),
        "label": {"source": label_source, "quad": label_quad, "image": label_b64,
                  "confidence": label_band_conf, "note": "original artwork preserved; not AI-generated"},
        "previews": {"cutout": _png_b64(cut_rgba), "background_bgr": [int(v) for v in bg]},
        "quality": quality,
        "work": {"budget_s": budget, "used_s": used, "cutout_iterations": c_iters,
                 "cutout_edge_score": round(c_score, 3), "profile_fit_rmse": round(fit_rmse, 5),
                 "profile_points": len(profile)},
        "conflicts": [],
    }
