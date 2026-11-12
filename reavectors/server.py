"""
reavectors local web server
===========================

A dependency-free (stdlib only) HTTP server that serves the drag-and-drop web UI
and exposes a small JSON/binary API:

    POST /api/vectorize           body = image bytes   -> JSON {svg, meta}
    POST /api/export?format=ai    body = image bytes   -> binary file

The web UI keeps everything local: the image is only ever sent to this server on
``127.0.0.1``, and results are cached in memory by content hash. Nothing is
uploaded anywhere else.

Run:  python -m reavectors.server         (then open http://127.0.0.1:8756)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .vectorize import vectorize
from .export import render_pdf, render_eps

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

# formats -> (content type, extension)
EXPORT_TYPES = {
    "svg": ("image/svg+xml", "svg"),
    "ai": ("application/pdf", "ai"),
    "pdf": ("application/pdf", "pdf"),
    "eps": ("application/postscript", "eps"),
}

_CACHE: "OrderedDict[str, object]" = OrderedDict()
_CACHE_MAX = 32


def _cache_get(key):
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key, value):
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
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
    server_version = "reavectors/0.2"
    protocol_version = "HTTP/1.1"

    # -- helpers -----------------------------------------------------------
    def _send(self, code, body: bytes, content_type="application/octet-stream",
              extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, fmt, *a):  # quieter logs
        sys.stderr.write("[reavectors] %s\n" % (fmt % a))

    # -- streaming refine (Server-Sent Events) ----------------------------
    def _sse_refine(self, data, params, refine):
        """
        Stream refinement progress as SSE, then a final `done` event carrying the
        SVG. This is what powers the UI's progress animation while the backend
        works for the whole time budget.
        """
        from .refine import auto_refine

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(obj):
            try:
                self.wfile.write(("data: " + json.dumps(obj) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                raise _ClientGone() from exc

        try:
            result, stats = auto_refine(
                data,
                budget=refine if refine and refine > 0 else 10.0,
                style=params["style"],
                max_size=params["max_size"],
                on_progress=lambda i, m, e: emit(
                    {"type": "progress", "pass": i, "match": m, "engine": e}
                ),
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
        except _ClientGone:
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            except Exception:  # noqa: BLE001
                pass

    # -- static files ------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            from . import vtracer_engine
            return self._json(200, {
                "ok": True,
                "app": "reavectors",
                "version": self.server_version,
                "features": ["refine", "sse", "vtracer" if vtracer_engine.available() else "potrace"],
            })
        if path in ("/", "/index.html"):
            return self._serve_file("index.html", "text/html; charset=utf-8")
        # only allow files inside WEB_DIR
        safe = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        if safe.startswith(".."):
            return self._send(403, b"forbidden", "text/plain")
        full = os.path.join(WEB_DIR, safe)
        if os.path.isfile(full):
            ctype = {
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".html": "text/html; charset=utf-8",
            }.get(os.path.splitext(full)[1], "application/octet-stream")
            return self._serve_file(safe, ctype)
        return self._send(404, b"not found", "text/plain")

    def _serve_file(self, rel, ctype):
        full = os.path.join(WEB_DIR, rel)
        try:
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, b"not found", "text/plain")

    # -- API ---------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length", 0) or 0)
        data = self.rfile.read(length) if length else b""
        if not data:
            return self._json(400, {"error": "empty request body"})

        detail_raw = qs.get("detail", [""])[0]
        params = {
            "engine": qs.get("engine", ["auto"])[0],
            "style": qs.get("style", ["logo"])[0],
            "detail": int(detail_raw) if detail_raw.strip().lstrip("-").isdigit() else None,
            "colors": _int(qs, "colors", 8),
            "alpha_threshold": _int(qs, "alpha_threshold", 128),
            "turdsize": _int(qs, "turdsize", 2),
            "alphamax": _float(qs, "alphamax", 1.0),
            "opttolerance": _float(qs, "opttolerance", 0.2),
            "max_size": _int(qs, "max_size", 1600),
        }
        refine = _float(qs, "refine", 0.0)
        key = hashlib.sha256(data).hexdigest() + json.dumps(
            {**params, "refine": refine}, sort_keys=True)

        def compute():
            """Return (result, stats); uses the refiner when refine > 0."""
            if refine and refine > 0:
                from .refine import auto_refine
                return auto_refine(data, budget=refine, style=params["style"],
                                   max_size=params["max_size"])
            return vectorize(data, **params), None

        try:
            if parsed.path == "/api/vectorize":
                result = _cache_get(key)
                stats = None
                if result is None:
                    result, stats = compute()
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
                    payload["match"] = stats.best_match
                    payload["passes"] = stats.iterations
                    payload["seconds"] = round(stats.seconds, 1)
                return self._json(200, payload)

            if parsed.path == "/api/refine":
                return self._sse_refine(data, params, refine)

            if parsed.path == "/api/export":
                fmt = (qs.get("format", ["svg"])[0] or "svg").lower()
                if fmt not in EXPORT_TYPES:
                    return self._json(400, {"error": f"unknown format {fmt!r}"})
                result = _cache_get(key)
                if result is None:
                    result, _ = compute()
                    _cache_put(key, result)
                if fmt == "svg":
                    body = result.to_svg().encode("utf-8")
                elif fmt in ("ai", "pdf"):
                    body = render_pdf(result)
                else:
                    body = render_eps(result)
                ctype, ext = EXPORT_TYPES[fmt]
                name = qs.get("name", ["reavectors"])[0] or "reavectors"
                safe_name = "".join(c for c in name if c.isalnum() or c in "._- ")[:60]
                disp = f'attachment; filename="{safe_name}.{ext}"'
                return self._send(200, body, ctype, {"Content-Disposition": disp})

            return self._json(404, {"error": "unknown endpoint"})
        except Exception as exc:  # keep the server alive, report cleanly
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def run(host=None, port=None):
    """
    Start the server.

    Host/port resolution (so the same code works locally and on a host like
    Render):
      * explicit arguments win,
      * else ``$HOST`` / ``$PORT`` env vars (Render provides ``$PORT``),
      * else bind ``0.0.0.0`` when ``$PORT`` is set (a hosted platform), or
        ``127.0.0.1`` for local use,
      * else port 8756.
    """
    host = host or os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    port = int(port or os.environ.get("PORT") or 8756)
    httpd = ThreadingHTTPServer((host, port), Handler)
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"reavectors server running at http://{shown}:{port}/  (bound {host}:{port})")
    print(f"serving UI from {WEB_DIR}")
    print("press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    cli_port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(port=cli_port)
