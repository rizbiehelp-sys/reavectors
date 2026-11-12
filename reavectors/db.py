"""
reavectors.db
=============

Optional Supabase backend (Postgres via the PostgREST HTTP API).

Two jobs:

1. **Conversion log** — one lightweight row per vectorize / refine / export,
   used by ``/api/stats``. No image data and no client identifiers are stored.
2. **Activity source** — a throttled read that keeps a *free* Supabase project
   from pausing (free projects pause after 7 days of inactivity). The Render
   app is pinged by the keep-alive workflow, and its health check touches the DB
   periodically, so the whole chain stays awake with no manual requests.

Design notes
------------
* Standard library only (``urllib``) — no extra dependency to install.
* Uses the **service-role** key from the environment; that key is never logged
  or committed. Row Level Security stays ON with no policies, so the public
  anon key cannot read the table.
* Strictly best-effort: a DB outage never breaks a conversion.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from . import config

_TIMEOUT = 6.0
_touch_lock = threading.Lock()
_last_touch = 0.0
_stats_lock = threading.Lock()
_stats_cache = {"at": 0.0, "value": None}


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers(prefer: Optional[str] = None) -> "dict[str, str]":
    h = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _request(method: str, path: str, body=None, prefer: Optional[str] = None,
             timeout: float = _TIMEOUT):
    url = f"{config.SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(prefer), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        status = resp.status
    return status, (json.loads(raw) if raw else None), headers


def _count_from_range(content_range: Optional[str]) -> int:
    """PostgREST returns '0-24/1234'; extract the total (1234)."""
    if not content_range or "/" not in content_range:
        return 0
    tail = content_range.split("/")[-1]
    try:
        return int(tail)
    except ValueError:
        return 0


def record_conversion(kind: str = "vectorize", **fields) -> None:
    """Insert one conversion row in a background thread (fire and forget)."""
    if not configured():
        return
    row = {"kind": kind}
    row.update({k: v for k, v in fields.items() if v is not None})

    def _work():
        try:
            _request("POST", "conversions", body=row, prefer="return=minimal")
        except Exception:  # noqa: BLE001 - never surface DB errors to the user
            pass

    threading.Thread(target=_work, daemon=True).start()


def stats() -> "dict":
    """Aggregate counts for /api/stats (cached, best-effort)."""
    if not configured():
        return {"ok": False, "reason": "database not configured"}
    now = time.time()
    with _stats_lock:
        cached = _stats_cache["value"]
        if cached is not None and now - _stats_cache["at"] < config.STATS_CACHE_SECONDS:
            return cached
    try:
        _, _, h_total = _request("GET", "conversions?select=id&limit=1", prefer="count=exact")
        total = _count_from_range(h_total.get("content-range"))
        day = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())
        _, _, h_today = _request(
            "GET", f"conversions?select=id&created_at=gte.{day}&limit=1", prefer="count=exact")
        today = _count_from_range(h_today.get("content-range"))
        _, rows, _ = _request("GET", "conversions?select=engine&limit=2000")
        engines: "dict[str, int]" = {}
        for r in (rows or []):
            key = r.get("engine") or "unknown"
            engines[key] = engines.get(key, 0) + 1
        value = {"ok": True, "total": total, "today": today, "engines": engines}
        with _stats_lock:
            _stats_cache["value"] = value
            _stats_cache["at"] = now
        return value
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": type(exc).__name__}


def touch() -> None:
    """
    Fire a throttled read in the background to register project activity.

    Non-blocking: health checks must stay fast, so the network call happens on a
    worker thread and at most once per ``SUPABASE_KEEPALIVE_SECONDS``.
    """
    if not configured():
        return
    global _last_touch
    now = time.time()
    with _touch_lock:
        if now - _last_touch < config.SUPABASE_KEEPALIVE_SECONDS:
            return
        _last_touch = now  # claim the slot before spawning

    def _work():
        try:
            _request("GET", "conversions?select=id&limit=1", timeout=8.0)
        except Exception:  # noqa: BLE001
            with _touch_lock:
                globals()["_last_touch"] = 0.0  # allow a retry next time

    threading.Thread(target=_work, daemon=True).start()
