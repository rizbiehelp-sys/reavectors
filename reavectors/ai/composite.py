"""
Product-scene compositing: keep the REAL product (label/sticker untouched) and
generate only the background.

Why: text-to-image models ignore the reference photo (Cloudflare flux-1-schnell)
and would re-invent the label. Compositing guarantees exact branding.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _border_color(arr: np.ndarray, b: int = 6) -> np.ndarray:
    edges = np.concatenate([arr[:b].reshape(-1, 3), arr[-b:].reshape(-1, 3),
                            arr[:, :b].reshape(-1, 3), arr[:, -b:].reshape(-1, 3)])
    return np.median(edges, axis=0)


def cutout(img: Image.Image, tol: float = 34.0) -> tuple[Image.Image, np.ndarray]:
    """Alpha-cut the product using the photo's border colour (works on plain backdrops)."""
    rgb = img.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    bg = _border_color(arr)
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    mask = (dist > tol)
    alpha = Image.fromarray((mask * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.7))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out, mask


def _gradient(size, top=(236, 240, 245), bottom=(196, 204, 214)) -> Image.Image:
    w, h = size
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((w, h))


def composite(product: Image.Image, background: Image.Image, size=(1024, 1024),
              scale: float = 0.72) -> Image.Image:
    W, H = size
    bg = background.convert("RGB").resize((W, H), Image.LANCZOS)

    # scale product to a comfortable height
    target_h = int(H * scale)
    ratio = target_h / max(1, product.height)
    prod = product.resize((max(1, int(product.width * ratio)), target_h), Image.LANCZOS)

    x = (W - prod.width) // 2
    y = int(H * 0.60) - prod.height // 2

    # soft ground shadow under the product
    shadow = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shadow)
    sw = int(prod.width * 0.85)
    sh = max(12, int(prod.height * 0.10))
    d.ellipse([(W - sw) // 2, y + prod.height - sh // 2, (W + sw) // 2, y + prod.height + sh // 2],
              fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    bg = Image.composite(black, bg, shadow.point(lambda v: int(v * 0.35)))

    bg.paste(prod, (x, y), prod)
    return bg


def build_scene(image_bytes: bytes, bg_bytes: bytes | None, prompt: str = "") -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    product, _ = cutout(img)
    if bg_bytes:
        bg = Image.open(io.BytesIO(bg_bytes))
    else:
        bg = _gradient((1024, 1024))
    out = composite(product, bg)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()