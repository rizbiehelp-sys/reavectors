"""
reavectors.security
===================

Security and load-control helpers used by the HTTP layer:

* Sliding-window per-IP rate limiting.
* A global concurrency cap so heavy tracing cannot exhaust the CPU.
* Input validation for uploaded images (format allow-list, dimension/pixel
  caps, decompression-bomb guard).
* A standard set of security response headers.

Kept dependency-light (stdlib + Pillow) so it runs identically on Windows and on
Linux hosts.
"""

from __future__ import annotations

import io
import threading
import time
from collections import defaultdict, deque
from typing import Optional, Tuple

from PIL import Image, UnidentifiedImageError

from . import config

# Guard against decompression bombs (a tiny file that expands to a huge bitmap).
Image.MAX_IMAGE_PIXELS = config.MAX_PIXELS

# Raster formats we will accept. (SVG is intentionally excluded: it is a vector
# script, not something Pillow should rasterise from untrusted input.)
ALLOWED_FORMATS = {
    "PNG", "JPEG", "JPG", "WEBP", "GIF", "BMP", "TIFF", "ICO", "PPM", "PBM", "PGM",
}


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per ``window`` seconds, per key."""

    def __init__(self, limit: int, window: float):
        self.limit = max(1, int(limit))
        self.window = float(window)
        self._hits: "dict[str, deque]" = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> Tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.limit:
                retry = int(self.window - (now - dq[0])) if dq else int(self.window)
                return False, max(1, retry)
            dq.append(now)
            return True, 0


# Module-level limiters (shared across requests in the process).
general_limiter = SlidingWindowLimiter(config.RATE_LIMIT, config.RATE_WINDOW)
refine_limiter = SlidingWindowLimiter(config.REFINE_RATE_LIMIT, config.RATE_WINDOW)

# Global cap on simultaneous heavy jobs. extra=1 for a normal vectorize, 2 for a
# refine (heavier, longer). Acquired with a short timeout so bursts queue or 503
# instead of melting the box.
heavy_gate = threading.BoundedSemaphore(config.MAX_CONCURRENCY)


def validate_image(data: bytes) -> Tuple[Optional[str], Optional[str]]:
    """
    Validate uploaded bytes as a supported raster image.

    Returns ``(image_format, None)`` on success or ``(None, reason)``.
    """
    if not data:
        return None, "empty request body"
    if len(data) > config.MAX_UPLOAD_BYTES:
        return None, f"file too large (limit {config.MAX_UPLOAD_MB} MB)"
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                return None, f"unsupported image format: {fmt or 'unknown'}"
            w, h = im.size
            if w <= 0 or h <= 0:
                return None, "invalid image dimensions"
            if max(w, h) > config.MAX_DIM:
                return None, f"image too large (max edge {config.MAX_DIM}px)"
            if w * h > config.MAX_PIXELS:
                return None, f"image too large (max {config.MAX_PIXELS} pixels)"
            im.verify()  # verifies the file is not truncated/corrupt
        return fmt, None
    except UnidentifiedImageError:
        return None, "not a recognised image"
    except Image.DecompressionBombError:
        return None, "image too large"
    except Exception as exc:  # noqa: BLE001 - never leak internals
        return None, f"invalid image ({type(exc).__name__})"


def security_headers() -> "dict[str, str]":
    """Baseline hardening headers for every response."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "X-XSS-Protection": "0",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        ),
    }
