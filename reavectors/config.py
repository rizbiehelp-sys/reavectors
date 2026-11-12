"""
reavectors.config
=================

Central configuration, read from environment variables with safe defaults.
Everything security- or scale-related lives here so it can be tuned per
deployment (locally or on the host) without touching code.
"""

from __future__ import annotations

import os


def _load_dotenv() -> None:
    """
    Minimal, dependency-free `.env` loader.

    Loads a `.env` file from the repo root (if present) into the process
    environment **without overriding** variables that are already set. On a host
    like Render there is no `.env` (secrets come from the platform), so this is a
    no-op there; locally it lets you keep secrets in one git-ignored file.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


_load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- upload / input limits -------------------------------------------------
MAX_UPLOAD_MB = _int("REAVECTORS_MAX_UPLOAD_MB", 12)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_PIXELS = _int("REAVECTORS_MAX_PIXELS", 40_000_000)   # decompression-bomb guard
MAX_DIM = _int("REAVECTORS_MAX_DIM", 8000)               # longest edge guard

# --- rate limiting (per client IP) ----------------------------------------
RATE_LIMIT = _int("REAVECTORS_RATE", 60)                 # requests / window
RATE_WINDOW = _int("REAVECTORS_RATE_WINDOW", 60)         # seconds
REFINE_RATE_LIMIT = _int("REAVECTORS_REFINE_RATE", 12)   # refine requests / window

# --- concurrency / compute caps -------------------------------------------
MAX_CONCURRENCY = _int("REAVECTORS_MAX_CONCURRENCY", 4)  # simultaneous heavy jobs
MAX_SIZE = _int("REAVECTORS_MAX_SIZE", 1600)             # tracing downscale cap
REFINE_MAX_SECONDS = _int("REAVECTORS_REFINE_MAX_SECONDS", 12)
REFINE_DEFAULT_SECONDS = _int("REAVECTORS_REFINE_DEFAULT_SECONDS", 10)
VTracer_TIMEOUT = _int("REAVECTORS_VTRACER_TIMEOUT", 60)

# --- result cache ----------------------------------------------------------
CACHE_SIZE = _int("REAVECTORS_CACHE_SIZE", 64)

# --- access control --------------------------------------------------------
# If set, every /api/* call must send "X-API-Key: <value>". The web UI is served
# with the key injected when this is set, so the public page keeps working only
# for people you give the link to. Leave empty for a public service.
API_KEY = os.environ.get("REAVECTORS_API_KEY", "").strip()

# Comma-separated extra origins allowed to call the API (besides same-origin).
CORS_ORIGINS = [o.strip() for o in os.environ.get("REAVECTORS_CORS_ORIGINS", "").split(",") if o.strip()]

# Trust X-Forwarded-For for the client IP only when we are genuinely behind a
# trusted reverse proxy (Render sets RENDER=true). Otherwise a direct caller
# could spoof the header and bypass per-IP rate limiting.
TRUST_PROXY = bool(os.environ.get("RENDER")) or os.environ.get("REAVECTORS_TRUST_PROXY", "") == "1"

# --- Supabase (optional backend database) ----------------------------------
# Point at a Supabase project to enable /api/stats and a conversion log. Uses
# the service-role key, kept ONLY in the host's environment (never in the repo).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
STATS_CACHE_SECONDS = _int("REAVECTORS_STATS_CACHE_SECONDS", 30)
# Activity interval that keeps a free Supabase project from pausing (7-day limit).
SUPABASE_KEEPALIVE_SECONDS = _int("REAVECTORS_SUPABASE_KEEPALIVE_SECONDS", 3600)
