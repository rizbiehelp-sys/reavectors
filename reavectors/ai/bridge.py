"""
Owner-only artifact bridge between Kaggle (GPU) and Render (serving).

Durable by default: if ``SUPABASE_URL`` + ``SUPABASE_SERVICE_KEY`` are set, jobs and
artifacts live in **Supabase Storage** (survive Render redeploys / restarts).
Otherwise it falls back to a local ``data/ai_bridge`` folder (ephemeral).

Flow (owner-only write; artifacts public for the studio):

    POST /api/ai/bridge/jobs              queue work
    GET  /api/ai/bridge/jobs?status=pending   Kaggle pulls
    POST /api/ai/bridge/jobs/<id>/claim       take one
    POST /api/ai/bridge/jobs/<id>/result      upload GLB/MP4
    GET  /api/ai/bridge/artifacts/<name>      serve (proxy, no CORS issues)

Kaggle must NOT serve public traffic; this is a job/artifact exchange, not an
inference endpoint.
"""

from __future__ import annotations

import datetime as _dt
import json
import mimetypes
import os
import threading
import urllib.error
import urllib.request
import uuid

from .. import config


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ArtifactBridge:
    """Local-filesystem bridge (ephemeral on Render; durable on a real disk)."""

    backend = "local"

    def __init__(self, root: str):
        self.root = root
        self.jobs_dir = os.path.join(root, "jobs")
        self.art_dir = os.path.join(root, "artifacts")
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.art_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _jp(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _read(self, job_id: str) -> dict:
        with open(self._jp(job_id), "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, job: dict) -> None:
        job["updated_at"] = _now()
        with open(self._jp(job["id"]), "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2)

    def submit(self, task, model, input_url=None, params=None):
        job = {"id": uuid.uuid4().hex, "task": task, "model": model, "input_url": input_url,
               "params": params or {}, "status": "pending", "created_at": _now()}
        with self._lock:
            self._write(job)
        return job

    def list(self, status=None, limit=50):
        out = []
        with self._lock:
            for name in sorted(os.listdir(self.jobs_dir)):
                if name.endswith(".json"):
                    try:
                        j = self._read(name[:-5])
                    except Exception:  # noqa: BLE001
                        continue
                    if status is None or j.get("status") == status:
                        out.append(j)
        out.sort(key=lambda j: j.get("created_at", ""))
        return out[:limit]

    def get(self, job_id):
        with self._lock:
            return self._read(job_id)

    def claim(self, job_id):
        with self._lock:
            j = self._read(job_id)
            if j.get("status") != "pending":
                return None
            j["status"] = "claimed"; j["claimed_at"] = _now(); self._write(j)
            return j

    def complete(self, job_id, filename, data, manifest=None):
        ext = os.path.splitext(filename or "")[1] or ".bin"
        artifact = job_id + ext
        with self._lock:
            j = self._read(job_id)
            with open(os.path.join(self.art_dir, artifact), "wb") as f:
                f.write(data)
            j.update({"status": "done", "artifact": artifact, "artifact_name": filename,
                      "bytes": len(data), "manifest": manifest})
            self._write(j)
        return {"artifact": artifact, "bytes": len(data)}

    def fail(self, job_id, error):
        with self._lock:
            j = self._read(job_id)
            j.update({"status": "failed", "error": error}); self._write(j)
            return j

    def set_meta(self, key, value):
        with self._lock:
            with open(os.path.join(self.art_dir, f"meta_{key}.json"), "w", encoding="utf-8") as f:
                json.dump(value, f)

    def get_meta(self, key):
        p = os.path.join(self.art_dir, f"meta_{key}.json")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def put_blob(self, name, data, ctype="application/octet-stream"):
        if os.path.basename(name) != name:
            raise ValueError("bad name")
        with self._lock:
            with open(os.path.join(self.art_dir, name), "wb") as f:
                f.write(data)
        return name

    def artifact_bytes(self, name):
        if os.path.basename(name) != name:
            return None
        path = os.path.join(self.art_dir, name)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()


class BridgeError(RuntimeError):
    pass


class SupabaseBridge:
    """Supabase-Storage-backed bridge (durable). Flat object names:
    ``job_<id>.json`` and ``art_<id><ext>``."""

    backend = "supabase"

    def __init__(self, url: str, key: str, bucket: str = "ai-bridge", transport=None):
        self.url = url.rstrip("/")
        self.key = key
        self.bucket = bucket
        self._transport = transport or self._http
        self._lock = threading.Lock()
        self._ensure_bucket()

    def _http(self, method, path, data=None, headers=None):
        req = urllib.request.Request(f"{self.url}/storage/v1{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "apikey": self.key, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.getcode(), r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise BridgeError(f"supabase network: {exc.reason}") from exc

    def _ensure_bucket(self):
        code, body = self._transport("POST", "/bucket",
                                     data=json.dumps({"id": self.bucket, "name": self.bucket,
                                                      "public": False}).encode(),
                                     headers={"Content-Type": "application/json"})
        if code >= 300 and b"already exists" not in (body or b"").lower() \
                and b"duplicate" not in (body or b"").lower():
            raise BridgeError(f"bucket create failed: {code} {body[:200]!r}")

    def _put(self, name, data, ctype="application/octet-stream"):
        code, body = self._transport("POST", f"/object/{self.bucket}/{name}", data=data,
                                     headers={"x-upsert": "true", "Content-Type": ctype})
        if code >= 300:
            raise BridgeError(f"put {name} failed: {code} {body[:200]!r}")

    def _get(self, name):
        code, body = self._transport("GET", f"/object/{self.bucket}/{name}")
        return None if code >= 300 else body

    def _names(self, prefix):
        code, body = self._transport(
            "POST", f"/object/list/{self.bucket}",
            data=json.dumps({"prefix": prefix, "limit": 1000, "offset": 0}).encode(),
            headers={"Content-Type": "application/json"})
        if code >= 300:
            return []
        try:
            items = json.loads(body or b"[]")
        except Exception:  # noqa: BLE001
            return []
        return [i.get("name") for i in items if i.get("name")]

    def _job_key(self, job_id):
        return f"job_{job_id}.json"

    def _write_job(self, job):
        job["updated_at"] = _now()
        self._put(self._job_key(job["id"]), json.dumps(job).encode(), "application/json")

    def _read_job(self, job_id):
        body = self._get(self._job_key(job_id))
        if body is None:
            raise FileNotFoundError(job_id)
        return json.loads(body)

    # -- interface ---------------------------------------------------------
    def submit(self, task, model, input_url=None, params=None):
        job = {"id": uuid.uuid4().hex, "task": task, "model": model, "input_url": input_url,
               "params": params or {}, "status": "pending", "created_at": _now()}
        with self._lock:
            self._write_job(job)
        return job

    def list(self, status=None, limit=50):
        out = []
        with self._lock:
            for name in self._names("job_"):
                # Supabase returns names relative to the prefix; restore the full key
                full = name if name.startswith("job_") else "job_" + name
                if not full.endswith(".json"):
                    continue
                body = self._get(full)
                if not body:
                    continue
                try:
                    j = json.loads(body)
                except Exception:  # noqa: BLE001
                    continue
                if status is None or j.get("status") == status:
                    out.append(j)
        out.sort(key=lambda j: j.get("created_at", ""))
        return out[:limit]

    def get(self, job_id):
        with self._lock:
            return self._read_job(job_id)

    def claim(self, job_id):
        with self._lock:
            j = self._read_job(job_id)
            if j.get("status") != "pending":
                return None
            j["status"] = "claimed"; j["claimed_at"] = _now(); self._write_job(j)
            return j

    def complete(self, job_id, filename, data, manifest=None):
        ext = os.path.splitext(filename or "")[1] or ".bin"
        artifact = f"art_{job_id}{ext}"
        ctype = mimetypes.guess_type("x" + ext)[0] or "application/octet-stream"
        with self._lock:
            j = self._read_job(job_id)
            self._put(artifact, data, ctype)
            j.update({"status": "done", "artifact": artifact, "artifact_name": filename,
                      "bytes": len(data), "manifest": manifest})
            self._write_job(j)
        return {"artifact": artifact, "bytes": len(data)}

    def fail(self, job_id, error):
        with self._lock:
            j = self._read_job(job_id)
            j.update({"status": "failed", "error": error}); self._write_job(j)
            return j

    def set_meta(self, key, value):
        with self._lock:
            self._put(f"meta_{key}.json", json.dumps(value).encode(), "application/json")

    def get_meta(self, key):
        body = self._get(f"meta_{key}.json")
        return json.loads(body) if body else None

    def put_blob(self, name, data, ctype="application/octet-stream"):
        if os.path.basename(name) != name:
            raise ValueError("bad name")
        with self._lock:
            self._put(name, data, ctype)
        return name

    def artifact_bytes(self, name):
        if os.path.basename(name) != name:
            return None
        return self._get(name)


_bridge = None
_bridge_note = ""


def get_bridge():
    """Supabase-backed when configured, else local."""
    global _bridge, _bridge_note
    if _bridge is not None:
        return _bridge
    bucket = getattr(config, "AI_BRIDGE_BUCKET", "ai-bridge")
    if getattr(config, "SUPABASE_URL", "") and getattr(config, "SUPABASE_SERVICE_KEY", ""):
        try:
            _bridge = SupabaseBridge(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY, bucket)
            _bridge_note = "supabase"
            return _bridge
        except Exception as exc:  # noqa: BLE001
            _bridge_note = f"supabase failed ({type(exc).__name__}); local fallback"
    if _bridge is None:
        _bridge = ArtifactBridge(config.AI_BRIDGE_DIR)
        _bridge_note = _bridge_note or "local"
    return _bridge


def bridge_backend() -> str:
    get_bridge()
    return getattr(_bridge, "backend", "local")