"""
reavectors local / hosted web server
====================================

A dependency-free (stdlib-only) HTTP server that serves the drag-and-drop web UI
and a small JSON/binary/streaming API, with production-oriented safeguards:

  * per-IP sliding-window rate limiting
  * a global concurrency cap so heavy tracing cannot exhaust the CPU
  * upload validation (format allow-list, size / dimension / pixel caps)
  * optional API-key gate
  * strict security response headers (CSP, nosniff, frame-deny, ...)

Routes
------
  GET  /                 the web UI
  GET  /api/health       liveness + build/feature info (always public)
  POST /api/vectorize    body=image  -> JSON {svg, meta}
  POST /api/refine       body=image  -> SSE progress stream, then `done`
  POST /api/export       body=image  -> binary file (.svg/.ai/.pdf/.eps)

Run:  python -m reavectors.server         (then open http://127.0.0.1:8756)
Env:  PORT / HOST are honoured (Render sets PORT).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, security, db
from .vectorize import vectorize
from .export import render_pdf, render_eps

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

EXPORT_TYPES = {
    "svg": ("image/svg+xml", "svg"),
    "ai": ("application/pdf", "ai"),
    "pdf": ("application/pdf", "pdf"),
    "eps": ("application/postscript", "eps"),
}

# formats that never need the API key
PUBLIC_PATHS = {"/api/health"}

_CACHE: "OrderedDict[str, object]" = OrderedDict()


def _cache_get(key):
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key, value):
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > config.CACHE_SIZE:
        _CACHE.popitem(last=False)


def _int(qs, name, default):
    try:
        return int(qs.get(name, [default])[0])
    except (TypeError, ValueError):
        return default


def _float(qs, name, default):
    try:
        return float(qs.get(name, [default])[0])
    except (TypeError, ValueError):
        return default


class _ClientGone(Exception):
    """Raised when the client closes a streaming connection mid-refine."""


class Handler(BaseHTTPRequestHandler):
    server_version = "reavectors/0.3"
    protocol_version = "HTTP/1.1"

    # -- helpers -----------------------------------------------------------
    def _client_ip(self) -> str:
        """Best-effort client IP (Render proxies via X-Forwarded-For)."""
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "?"

    def _send(self, code, body: bytes, content_type="application/octet-stream",
              extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in security.security_headers().items():
            self.send_header(k, v)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, extra_headers=None):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json", extra_headers)

    def _error(self, code, message, extra_headers=None):
        self._json(code, {"error": message}, extra_headers)

    def log_message(self, fmt, *a):  # quieter logs
        sys.stderr.write("[reavectors] %s %s\n" % (self._client_ip(), fmt % a))

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin and (origin in config.CORS_ORIGINS):
            return {"Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
                    "Access-Control-Allow-Methods": "POST, GET, OPTIONS"}
        return {}

    # -- static files ------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            from . import vtracer_engine
            db.touch()  # throttled, non-blocking activity ping (keeps Supabase awake)
            return self._json(200, {
                "ok": True,
                "app": "reavectors",
                "version": self.server_version,
                "db": "on" if db.configured() else "off",
                "features": ["refine", "sse", "stats",
                             "vtracer" if vtracer_engine.available() else "potrace"],
                "limits": {
                    "max_upload_mb": config.MAX_UPLOAD_MB,
                    "max_dim": config.MAX_DIM,
                    "rate_per_min": config.RATE_LIMIT,
                    "max_concurrency": config.MAX_CONCURRENCY,
                },
            })
        if path == "/api/stats":
            return self._json(200, db.stats())
        if path in ("/", "/index.html"):
            return self._serve_index()
        safe = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        if safe.startswith(".."):
            return self._error(403, "forbidden")
        full = os.path.join(WEB_DIR, safe)
        if os.path.isfile(full):
            ctype = {
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".html": "text/html; charset=utf-8",
            }.get(os.path.splitext(full)[1], "application/octet-stream")
            try:
                with open(full, "rb") as f:
                    return self._send(200, f.read(), ctype)
            except OSError:
                pass
        return self._error(404, "not found")

    def _serve_index(self):
        try:
            with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                html = f.read().decode("utf-8")
        except OSError:
            return self._error(404, "not found")
        # Inject the API key (if configured) so the bundled UI keeps working.
        html = html.replace("__REAVECTORS_API_KEY__", config.API_KEY)
        return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def do_OPTIONS(self):
        cors = self._cors_headers()
        if not cors:
            return self._error(403, "CORS not allowed")
        self.send_response(204)
        for k, v in {**security.security_headers(), **cors}.items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- API ---------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        ip = self._client_ip()

        # rate limit every API call
        allowed, retry = security.general_limiter.check(ip)
        if not allowed:
            return self._error(429, "rate limit exceeded", {"Retry-After": str(retry)})

        # optional API-key gate
        if config.API_KEY and parsed.path not in PUBLIC_PATHS:
            if self.headers.get("X-API-Key", "") != config.API_KEY:
                return self._error(401, "missing or invalid API key")

        # body with a hard size cap
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return self._error(400, "bad Content-Length")
        if length <= 0:
            return self._error(400, "empty request body")
        if length > config.MAX_UPLOAD_BYTES:
            return self._error(413, f"file too large (limit {config.MAX_UPLOAD_MB} MB)")
        data = self.rfile.read(length)

        # validate it is a real, supported, reasonably sized image
        _fmt, reason = security.validate_image(data)
        if reason:
            return self._error(415, reason)

        is_refine = parsed.path == "/api/refine"
        if is_refine:
            ok, retry = security.refine_limiter.check(ip)
            if not ok:
                return self._error(429, "refine rate limit exceeded", {"Retry-After": str(retry)})

        params = {
            "engine": qs.get("engine", ["auto"])[0],
            "style": qs.get("style", ["logo"])[0],
            "detail": _int(qs, "detail", 16) if qs.get("detail") else None,
            "colors": max(1, min(256, _int(qs, "colors", 8))),
            "alpha_threshold": max(1, min(254, _int(qs, "alpha_threshold", 128))),
            "turdsize": max(0, min(64, _int(qs, "turdsize", 2))),
            "alphamax": min(1.334, max(0.0, _float(qs, "alphamax", 1.0))),
            "opttolerance": min(5.0, max(0.0, _float(qs, "opttolerance", 0.2))),
            "max_size": max(256, min(config.MAX_SIZE, _int(qs, "max_size", config.MAX_SIZE))),
        }
        refine = min(config.REFINE_MAX_SECONDS,
                     max(0.0, _float(qs, "refine", 0.0))) or 0.0
        key = hashlib.sha256(data).hexdigest() + json.dumps(
            {**params, "refine": refine}, sort_keys=True)

        if parsed.path == "/api/refine":
            return self._sse_refine(data, params, refine, ip)

        if parsed.path == "/api/vectorize":
            return self._vectorize(data, params, refine, key)

        if parsed.path == "/api/export":
            return self._export(data, params, refine, key, qs)

        return self._error(404, "unknown endpoint")

    # -- handlers ----------------------------------------------------------
    def _vectorize(self, data, params, refine, key):
        if not security.heavy_gate.acquire(timeout=20):
            return self._error(503, "server busy, please retry")
        try:
            result = _cache_get(key)
            stats = None
            if result is None:
                if refine and refine > 0:
                    from .refine import auto_refine
                    result, stats = auto_refine(data, budget=refine,
                                                style=params["style"], max_size=params["max_size"])
                else:
                    result = vectorize(data, **params)
                _cache_put(key, result)
            payload = {
                "svg": result.to_svg(),
                "engine": result.engine,
                "width": result.width,
                "height": result.height,
                "colors": result.color_count,
                "figures": result.figure_count,
                "subpaths": result.path_count,
                "palette": ["#%02X%02X%02X" % l.color for l in result.layers if l.figures],
            }
            if stats is not None:
                payload |= {"match": stats.best_match, "passes": stats.iterations,
                            "seconds": round(stats.seconds, 1)}
            db.record_conversion(
                kind="refine" if stats is not None else "vectorize",
                engine=result.engine, style=params["style"], colors=result.color_count,
                figures=result.figure_count, subpaths=result.path_count,
                match_pct=getattr(stats, "best_match", None),
                seconds=round(stats.seconds, 1) if stats is not None else None,
            )
            return self._json(200, payload, self._cors_headers())
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}")
        finally:
            security.heavy_gate.release()

    def _export(self, data, params, refine, key, qs):
        fmt = (qs.get("format", ["svg"])[0] or "svg").lower()
        if fmt not in EXPORT_TYPES:
            return self._error(400, f"unknown format {fmt!r}")
        if not security.heavy_gate.acquire(timeout=20):
            return self._error(503, "server busy, please retry")
        try:
            result = _cache_get(key)
            if result is None:
                if refine and refine > 0:
                    from .refine import auto_refine
                    result, _ = auto_refine(data, budget=refine,
                                            style=params["style"], max_size=params["max_size"])
                else:
                    result = vectorize(data, **params)
                _cache_put(key, result)
            if fmt == "svg":
                body = result.to_svg().encode("utf-8")
            elif fmt in ("ai", "pdf"):
                body = render_pdf(result)
            else:
                body = render_eps(result)
            ctype, ext = EXPORT_TYPES[fmt]
            db.record_conversion(kind="export", engine=result.engine, fmt=fmt,
                                 style=params["style"], colors=result.color_count)
            name = "".join(c for c in (qs.get("name", ["reavectors"])[0] or "reavectors")
                           if c.isalnum() or c in "._- ")[:60] or "reavectors"
            return self._send(200, body, ctype,
                              {**self._cors_headers(),
                               "Content-Disposition": f'attachment; filename="{name}.{ext}"'})
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}")
        finally:
            security.heavy_gate.release()

    # -- streaming refine (Server-Sent Events) -----------------------------
    def _sse_refine(self, data, params, refine, ip):
        if not security.heavy_gate.acquire(timeout=20):
            return self._error(503, "server busy, please retry")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        for k, v in security.security_headers().items():
            self.send_header(k, v)
        for k, v in self._cors_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.close_connection = True

        def emit(obj):
            try:
                self.wfile.write(("data: " + json.dumps(obj) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                raise _ClientGone() from exc

        try:
            from .refine import auto_refine
            result, stats = auto_refine(
                data,
                budget=refine if refine > 0 else config.REFINE_DEFAULT_SECONDS,
                style=params["style"],
                max_size=params["max_size"],
                on_progress=lambda i, m, e: emit(
                    {"type": "progress", "pass": i, "match": m, "engine": e}),
            )
            emit({
                "type": "done",
                "svg": result.to_svg(),
                "engine": result.engine,
                "width": result.width,
                "height": result.height,
                "colors": result.color_count,
                "figures": result.figure_count,
                "subpaths": result.path_count,
                "match": stats.best_match,
                "passes": stats.iterations,
                "seconds": round(stats.seconds, 1),
                "palette": ["#%02X%02X%02X" % l.color for l in result.layers if l.figures],
            })
            db.record_conversion(kind="refine", engine=result.engine, style=params["style"],
                                 colors=result.color_count, figures=result.figure_count,
                                 subpaths=result.path_count, match_pct=stats.best_match,
                                 seconds=round(stats.seconds, 1))
        except _ClientGone:
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                emit({"type": "error", "error": f"{type(exc).__name__}"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            security.heavy_gate.release()


def run(host=None, port=None):
    """
    Start the server.

    Host/port resolution (so the same code works locally and on a host like
    Render): explicit args, then ``$HOST`` / ``$PORT`` env, then ``0.0.0.0``
    (when ``$PORT`` is set) or ``127.0.0.1``, then port 8756.
    """
    host = host or os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    port = int(port or os.environ.get("PORT") or 8756)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"reavectors server running at http://{shown}:{port}/  (bound {host}:{port})")
    print(f"serving UI from {WEB_DIR}")
    print(f"limits: {config.MAX_UPLOAD_MB}MB upload, {config.RATE_LIMIT}/min, "
          f"concurrency {config.MAX_CONCURRENCY}, refine<= {config.REFINE_MAX_SECONDS}s"
          + (", API key REQUIRED" if config.API_KEY else ""))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    cli_port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(port=cli_port)
