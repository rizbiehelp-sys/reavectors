"""
Owner-only artifact bridge between Kaggle (GPU) and Render (serving).

Kaggle must NOT serve public traffic (ToS) and cannot be called live. Instead the
owner's Kaggle notebook:

    1. GET  /api/ai/bridge/jobs?status=pending   -> pull queued work
    2. POST /api/ai/bridge/jobs/<id>/claim       -> take one job
    3. ... run the model on the T4 ...
    4. POST /api/ai/bridge/jobs/<id>/result      -> upload GLB/MP4 + manifest
    5. Website loads GET /api/ai/bridge/artifacts/<id>.<ext>

All write/read-of-jobs endpoints require ``X-Bridge-Key`` (``AI_BRIDGE_KEY``);
artifacts are public so the studio can display them. This is a job/artifact
exchange, not a public inference endpoint.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import uuid

from .. import config


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ArtifactBridge:
    def __init__(self, root: str):
        self.root = root
        self.jobs_dir = os.path.join(root, "jobs")
        self.art_dir = os.path.join(root, "artifacts")
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.art_dir, exist_ok=True)
        self._lock = threading.Lock()

    # -- internals ---------------------------------------------------------
    def _jp(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _read(self, job_id: str) -> dict:
        with open(self._jp(job_id), "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, job: dict) -> None:
        job["updated_at"] = _now()
        with open(self._jp(job["id"]), "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2)

    # -- API ---------------------------------------------------------------
    def submit(self, task: str, model: str, input_url: str = None, params: dict = None) -> dict:
        job = {"id": uuid.uuid4().hex, "task": task, "model": model,
               "input_url": input_url, "params": params or {},
               "status": "pending", "created_at": _now()}
        with self._lock:
            self._write(job)
        return job

    def list(self, status: str = None, limit: int = 50) -> list:
        out = []
        with self._lock:
            for name in sorted(os.listdir(self.jobs_dir)):
                if not name.endswith(".json"):
                    continue
                try:
                    j = self._read(name[:-5])
                except Exception:  # noqa: BLE001
                    continue
                if status is None or j.get("status") == status:
                    out.append(j)
        out.sort(key=lambda j: j.get("created_at", ""))
        return out[:limit]

    def get(self, job_id: str) -> dict:
        with self._lock:
            return self._read(job_id)

    def claim(self, job_id: str) -> dict:
        with self._lock:
            j = self._read(job_id)
            if j.get("status") != "pending":
                return None
            j["status"] = "claimed"
            j["claimed_at"] = _now()
            self._write(j)
            return j

    def complete(self, job_id: str, filename: str, data: bytes, manifest: dict = None) -> dict:
        ext = os.path.splitext(filename or "")[1] or ".bin"
        artifact_name = job_id + ext
        with self._lock:
            j = self._read(job_id)
            with open(os.path.join(self.art_dir, artifact_name), "wb") as f:
                f.write(data)
            j["status"] = "done"
            j["artifact"] = artifact_name
            j["artifact_name"] = filename
            j["bytes"] = len(data)
            j["manifest"] = manifest
            self._write(j)
        return {"artifact": artifact_name, "bytes": len(data)}

    def fail(self, job_id: str, error: str) -> dict:
        with self._lock:
            j = self._read(job_id)
            j["status"] = "failed"
            j["error"] = error
            self._write(j)
            return j

    def artifact_path(self, artifact_name: str) -> str:
        if os.path.basename(artifact_name) != artifact_name:
            return None
        path = os.path.join(self.art_dir, artifact_name)
        return path if os.path.isfile(path) else None


_bridge = None


def get_bridge() -> ArtifactBridge:
    global _bridge
    if _bridge is None:
        _bridge = ArtifactBridge(config.AI_BRIDGE_DIR)
    return _bridge