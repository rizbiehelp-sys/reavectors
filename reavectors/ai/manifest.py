"""
Reproducible manifests + versioned job workspaces.

Kaggle's filesystem does not survive a session restart, so every job writes into
its own versioned folder (``<root>/<run_id>__<model>/``) with a manifest. Export
the folder (or push it to the artifact bridge / bucket) before the session ends.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil

from . import registry


def _utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class JobWorkspace:
    def __init__(self, root: str, model_id: str, prefix: str = ""):
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}-{os.urandom(3).hex()}"
        self.dir = os.path.join(root, f"{self.run_id}__{(prefix or model_id)}")
        os.makedirs(self.dir, exist_ok=True)

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def save_output(self, name: str, *, data: bytes = None, src: str = None) -> str:
        dest = self.path(name)
        if src and os.path.abspath(src) != os.path.abspath(dest):
            shutil.copyfile(src, dest)
        elif data is not None:
            with open(dest, "wb") as f:
                f.write(data)
        return dest

    def write_manifest(self, data: dict) -> str:
        dest = self.path("manifest.json")
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return dest

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "dir": self.dir}


def run_manifest(model_id: str, *, inputs: dict, params: dict, outputs: list,
                 timings: dict, env: dict = None, ok: bool = True,
                 error: str = None, gpu: str = None) -> dict:
    spec = registry.get(model_id)
    files = []
    for p in outputs:
        if p and os.path.isfile(p):
            files.append({"path": os.path.basename(p), "bytes": os.path.getsize(p),
                          "sha256": sha256_file(p)})
    return {
        "schema": "reavectors.run-manifest/1",
        "created_at": _utc(),
        "ok": ok,
        "error": error,
        "gpu": gpu,
        "model": spec.to_dict(),
        "inputs": inputs,
        "params": params or {},
        "timings": timings or {},
        "outputs": files,
        "env": env or {},
    }


def model_manifest() -> dict:
    return registry.manifest()


def persist(src_dir: str, dest_root: str) -> str:
    """Copy a finished workspace somewhere durable (e.g. a synced Drive/bucket)."""
    os.makedirs(dest_root, exist_ok=True)
    dest = os.path.join(dest_root, os.path.basename(src_dir))
    if os.path.abspath(src_dir) != os.path.abspath(dest):
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(src_dir, dest)
    return dest