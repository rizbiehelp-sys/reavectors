"""
reavectors.config
=================

Central configuration, read from environment variables with safe defaults.
Everything security- or scale-related lives here so it can be tuned per
deployment (locally or on the host) without touching code.
"""

from __future__ import annotations

import os


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

# --- Supabase (optional backend database) ----------------------------------
# Point at a Supabase project to enable /api/stats and a conversion log. Uses
# the service-role key, kept ONLY in the host's environment (never in the repo).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
STATS_CACHE_SECONDS = _int("REAVECTORS_STATS_CACHE_SECONDS", 30)
# Activity interval that keeps a free Supabase project from pausing (7-day limit).
SUPABASE_KEEPALIVE_SECONDS = _int("REAVECTORS_SUPABASE_KEEPALIVE_SECONDS", 3600)
