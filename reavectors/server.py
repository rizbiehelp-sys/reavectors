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
import hmac
import json
import os
import re
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


def _parse_multipart(body: bytes, boundary: str) -> "dict[str, bytes]":
    """Minimal multipart/form-data parser -> {field_name: raw_bytes}."""
    delim = b"--" + boundary.encode("latin-1")
    fields: "dict[str, bytes]" = {}
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].rstrip(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        name = None
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-disposition"):
                for seg in line.split(b";"):
                    seg = seg.strip()
                    if seg.startswith(b"name="):
                        name = seg[5:].strip(b'"').decode("latin-1", "replace")
        if name:
            fields[name] = content
    return fields


class _ClientGone(Exception):
    """Raised when the client closes a streaming connection mid-refine."""


class Handler(BaseHTTPRequestHandler):
    server_version = "reavectors/0.3"
    protocol_version = "HTTP/1.1"

    # -- helpers -----------------------------------------------------------
    def _client_ip(self) -> str:
        """
        Client IP used for rate limiting.

        We sit behind exactly one trusted proxy (Render), which *appends* the
        real client address to ``X-Forwarded-For``. The trustworthy value is
        therefore the **last** hop; taking the first hop would let a caller send
        a spoofed ``X-Forwarded-For`` and bypass per-IP rate limiting.
        """
        if config.TRUST_PROXY:
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                parts = [p.strip() for p in xff.split(",") if p.strip()]
                if parts:
                    return parts[-1]
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
        if path.startswith("/api/ai/"):
            return self._handle_ai("GET", urlparse(self.path),
                                   parse_qs(urlparse(self.path).query), self._client_ip())
        if path in ("/", "/index.html"):
            return self._serve_index()
        # Confine static file reads to WEB_DIR: resolve the real path and require
        # it to stay under WEB_DIR. This blocks both `../` traversal and Windows
        # absolute-path tricks (e.g. "/C:/Windows/win.ini" via os.path.join).
        base = os.path.realpath(WEB_DIR)
        safe = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        full = os.path.realpath(os.path.join(base, safe))
        if full != base and not full.startswith(base + os.sep):
            return self._error(404, "not found")
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
                    body = f.read()
                if ctype.startswith("text/html"):
                    # keep the bundled UI working when an API key is configured
                    body = body.decode("utf-8").replace("__REAVECTORS_API_KEY__", config.API_KEY).encode("utf-8")
                return self._send(200, body, ctype)
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

        # optional API-key gate (constant-time compare to avoid timing leaks)
        if config.API_KEY and parsed.path not in PUBLIC_PATHS:
            provided = self.headers.get("X-API-Key", "")
            if not hmac.compare_digest(provided, config.API_KEY):
                return self._error(401, "missing or invalid API key")

        # AI Studio endpoints (JSON / binary bodies, not images) — own size caps
        if parsed.path.startswith("/api/ai/"):
            return self._handle_ai("POST", parsed, qs, ip)

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

    # -- AI Studio route dispatch -----------------------------------------
    def _ai_user(self) -> str:
        uid = self.headers.get("X-User-Id", "")
        if re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", uid or ""):
            return "u:" + uid
        return "anon:" + hashlib.sha256(self._client_ip().encode()).hexdigest()[:16]

    def _ai_admin(self) -> bool:
        return bool(config.AI_ADMIN_KEY) and hmac.compare_digest(
            self.headers.get("X-Admin-Key", ""), config.AI_ADMIN_KEY)

    def _read_bounded(self, max_bytes):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return None
        if length < 0 or length > max_bytes:
            self.close_connection = True
            return None
        return self.rfile.read(length) if length else b""

    def _read_json_bounded(self, max_bytes):
        data = self._read_bounded(max_bytes)
        if data is None:
            return None
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _handle_ai(self, method, parsed, qs, ip):
        if not config.AI_ENABLED:
            return self._error(404, "AI studio is disabled")
        from .ai.service import get_service
        svc = get_service()
        user = self._ai_user()
        admin = self._ai_admin()
        parts = [p for p in parsed.path[len("/api/ai/"):].split("/") if p]
        try:
            if method == "GET":
                if parts == ["capacity"]:
                    return self._json(200, svc.capacity()[1])
                if parts == ["models"]:
                    return self._json(200, svc.models()[1])
                if len(parts) == 3 and parts[0] == "product3d" and parts[1] == "hosted":
                    if parts[2] == "asset":
                        return self._hosted_asset(qs.get("url", [""])[0])
                    st, obj = svc.hosted3d_status(user, parts[2])
                    return self._json(st, obj)
                if parts == ["loras"]:
                    return self._json(200, svc.loras(user)[1])
                if parts == ["jobs", "history"]:
                    return self._json(200, svc.history(user)[1])
                if parts == ["tripo", "balance"]:
                    if not admin:
                        return self._error(403, "admin only")
                    return self._json(200, svc.tripo_balance()[1])
                if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "result":
                    path, err = svc.result_file(parts[1], user)
                    if err:
                        return self._error(404, err)
                    try:
                        with open(path, "rb") as fh:
                            body = fh.read()
                    except OSError:
                        return self._error(500, "could not read result")
                    return self._send(200, body, "model/gltf-binary", {
                        "Content-Disposition": f'attachment; filename="{parts[1]}.glb"',
                        **self._cors_headers()})
                if len(parts) == 2 and parts[0] == "jobs":
                    st, obj = svc.get(user, parts[1], admin)
                    return self._json(st, obj)
            elif method == "POST":
                if parts == ["product3d"]:
                    return self._product3d(svc, user, qs)
                if parts == ["product3d", "hosted"]:
                    return self._product3d_hosted(svc, user)
                if parts == ["3d"]:
                    data = self._read_bounded(config.MAX_UPLOAD_BYTES)
                    if data is None:
                        return self._error(413, "image too large")
                    filename = qs.get("filename", ["input.png"])[0] or "input.png"
                    st, obj = svc.submit_3d(user, data, filename, {})
                    return self._json(st, obj, {"Location": f"/api/ai/jobs/{obj.get('job_id','')}"})
                if parts == ["jobs"]:
                    body = self._read_json_bounded(64 * 1024)
                    if body is None:
                        return self._error(413, "request body too large")
                    st, obj = svc.submit(user, body, self.headers.get("Idempotency-Key"))
                    return self._json(st, obj, {"Location": f"/api/ai/jobs/{obj.get('job_id','')}"})
                if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel":
                    st, obj = svc.cancel(user, parts[1])
                    return self._json(st, obj)
                if parts == ["loras", "upload"]:
                    data = self._read_bounded(config.AI_MAX_LORA_BYTES)
                    if data is None:
                        return self._error(413, "LoRA upload too large")
                    params = {k: qs.get(k, [None])[0] for k in
                              ("name", "base", "trigger", "weight", "license", "source_url")}
                    filename = qs.get("filename", [""])[0]
                    st, obj = svc.upload_lora(user, filename, params, data)
                    return self._json(st, obj)
            elif method == "DELETE":
                if len(parts) == 2 and parts[0] == "loras":
                    st, obj = svc.delete_lora(user, parts[1])
                    return self._json(st, obj)
            return self._error(404, "unknown AI endpoint")
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}")

    def _product3d_hosted(self, svc, user):
        """Submit the photo (+ optional back/left/right) to the hosted Hunyuan Pro API."""
        import base64
        ctype = self.headers.get("Content-Type", "")
        data = self._read_bounded(config.MAX_UPLOAD_BYTES * 3)
        if data is None:
            return self._error(413, "upload too large")
        if "multipart/form-data" not in ctype:
            return self._error(415, "expected multipart/form-data")
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip().strip('"')
        if not boundary:
            return self._error(400, "missing multipart boundary")
        fields = _parse_multipart(data, boundary)
        image = fields.get("image")
        if not image:
            return self._error(400, "missing 'image' field")

        def data_url(bs: bytes) -> str:
            if bs[:3] == b"\xff\xd8\xff":
                fmt = "jpeg"
            elif bs[:8] == b"\x89PNG\r\n\x1a\n":
                fmt = "png"
            elif bs[:4] == b"RIFF" and bs[8:12] == b"WEBP":
                fmt = "webp"
            else:
                fmt = "png"
            return f"data:image/{fmt};base64," + base64.b64encode(bs).decode("ascii")

        model = (fields.get("model") or b"").decode("utf-8", "replace") or None
        pbr_raw = fields.get("enable_pbr")
        enable_pbr = None if pbr_raw is None else (pbr_raw.decode("utf-8", "replace").lower()
                                                   in ("1", "true", "on", "yes"))
        generate_type = (fields.get("generate_type") or b"Normal").decode("utf-8", "replace")
        extra = [{"view_type": vt, "view_image": data_url(fields[vt])}
                 for vt in ("back", "left", "right") if fields.get(vt)]
        multi = None
        if extra:
            multi = [{"view_type": "front", "view_image": data_url(image)}] + extra
        st, obj = svc.hosted3d_submit(user, image, model=model, enable_pbr=enable_pbr,
                                      generate_type=generate_type, multi_view_images=multi)
        return self._json(st, obj, self._cors_headers())

    def _hosted_asset(self, url: str):
        """SSRF-guarded proxy for the generated GLB (viewer + download, CORS-safe)."""
        import urllib.parse
        import urllib.request
        if not url:
            return self._error(400, "missing url")
        try:
            p = urllib.parse.urlparse(url)
        except Exception:  # noqa: BLE001
            return self._error(400, "bad url")
        host = p.hostname or ""
        allowed = config.AI_3DAS_ASSET_HOSTS
        if p.scheme != "https" or not (host == allowed or host.endswith("." + allowed)):
            return self._error(403, "asset host not allowed")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "reavectors/0.3"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read(120 * 1024 * 1024 + 1)
            if len(body) > 120 * 1024 * 1024:
                return self._error(413, "asset too large")
        except Exception as exc:  # noqa: BLE001
            return self._error(502, f"asset fetch failed: {type(exc).__name__}")
        return self._send(200, body, "model/gltf-binary",
                          {"Content-Disposition": 'inline; filename="model.glb"'})

    def _product3d(self, svc, user, qs=None):
        """
        Multipart: image (required) + label (optional) + quad/material/mode.

        ``?refine=<seconds>`` (10-120, default PRODUCT3D_REFINE_SECONDS) sets the
        refinement budget. ``?stream=1`` (or Accept: text/event-stream) streams
        progress as Server-Sent Events, then a final ``done`` with the spec.
        """
        qs = qs or {}
        ctype = self.headers.get("Content-Type", "")
        data = self._read_bounded(config.MAX_UPLOAD_BYTES * 3)
        if data is None:
            return self._error(413, "upload too large")
        if "multipart/form-data" not in ctype:
            return self._error(415, "expected multipart/form-data")
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip().strip('"')
        if not boundary:
            return self._error(400, "missing multipart boundary")
        fields = _parse_multipart(data, boundary)
        image = fields.get("image")
        if not image:
            return self._error(400, "missing 'image' field")
        label = fields.get("label")
        quad = None
        if fields.get("quad"):
            try:
                quad = json.loads(fields["quad"].decode("utf-8"))
            except Exception:  # noqa: BLE001
                quad = None
        material = (fields.get("material") or b"auto").decode("utf-8", "replace")
        mode = (fields.get("mode") or b"single").decode("utf-8", "replace")

        raw = _float(qs, "refine", float(config.PRODUCT3D_REFINE_SECONDS))
        budget = max(config.PRODUCT3D_REFINE_MIN, min(config.PRODUCT3D_REFINE_MAX, raw))

        want_stream = ("stream" in qs) or ("text/event-stream" in self.headers.get("Accept", ""))
        if not want_stream:
            st, obj = svc.product3d(user, image, label_bytes=label, quad=quad,
                                    material=material, mode=mode, budget=budget)
            return self._json(st, obj, self._cors_headers())
        return self._sse_product3d(svc, user, image, label, quad, material, mode, budget)

    def _sse_product3d(self, svc, user, image, label, quad, material, mode, budget):
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
            st, obj = svc.product3d(user, image, label_bytes=label, quad=quad,
                                    material=material, mode=mode, budget=budget,
                                    on_progress=emit)
            if st == 200:
                emit({"type": "done", "spec": obj})
            else:
                emit({"type": "error", "error": obj.get("error", "failed")})
        except _ClientGone:
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                emit({"type": "error", "error": f"{type(exc).__name__}"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            security.heavy_gate.release()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        ip = self._client_ip()
        allowed, retry = security.general_limiter.check(ip)
        if not allowed:
            return self._error(429, "rate limit exceeded", {"Retry-After": str(retry)})
        if config.API_KEY and not hmac.compare_digest(self.headers.get("X-API-Key", ""), config.API_KEY):
            return self._error(401, "missing or invalid API key")
        if parsed.path.startswith("/api/ai/"):
            return self._handle_ai("DELETE", parsed, qs, ip)
        return self._error(404, "not found")

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
