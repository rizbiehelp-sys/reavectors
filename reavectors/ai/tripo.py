"""
Tripo hosted image->3D adapter (PAID; opt-in).

This is the "hosted fallback" provider from the architecture: real textured 3D
meshes (glTF/GLB, quads/triangles, PBR) instead of the browser's silhouette
extrusion. It is **disabled by default** and costs real money.

Cost: Tripo pricing is 1 credit = $0.01 USD; image->3D is 20-30 credits
(~US$0.20-0.30) per model. A per-job cost guard (`AI_TRIPO_MAX_USD_PER_JOB`) must
pass before a task is created (see `check_cost`).

Auth: requires the **secret** API key (`tsk_...`). A client id (`tcli_...`)
does NOT authenticate the OpenAPI and is rejected up front.

The exact success envelopes are marked VERIFY: they were derived from Tripo's
public docs and the error shape observed from the live API, but a paid call was
not made to confirm them. All network access goes through an injectable
transport so this module is fully unit-testable offline.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Optional

from .. import config


class TripoError(RuntimeError):
    pass


class TripoAuthError(TripoError):
    pass


def _default_transport(method: str, url: str, headers: dict, body: bytes, timeout: float):
    """Return (status_code, response_dict). Raises on transport errors."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:  # noqa: F821
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"message": raw.decode("utf-8", "replace")}


class TripoClient:
    def __init__(self, api_key: str = None, base: str = None, model_version: str = None,
                 texture_quality: str = None, timeout: float = 60.0, transport=None):
        self.api_key = (api_key if api_key is not None else config.AI_TRIPO_API_KEY).strip()
        self.base = (base or config.AI_TRIPO_BASE).rstrip("/")
        self.model_version = model_version or config.AI_TRIPO_MODEL
        self.texture_quality = texture_quality or config.AI_TRIPO_TEXTURE_QUALITY
        self.timeout = timeout
        self._transport = transport or _default_transport
        if not self.api_key:
            raise TripoAuthError("AI_TRIPO_API_KEY is not set")
        if not self.api_key.startswith("tsk_"):
            raise TripoAuthError(
                "Tripo needs the SECRET key (tsk_...). A client id (tcli_...) does not "
                "authenticate the OpenAPI — get the secret key from the Tripo API keys page.")

    # ---- low level ------------------------------------------------------
    def _json(self, method: str, path: str, payload=None):
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, data = self._transport(method, url, headers, body, self.timeout)
        if status == 401:
            raise TripoAuthError(data.get("message") or "unauthorized")
        if status >= 400:
            raise TripoError(f"HTTP {status}: {data.get('message', data)}")
        return data

    def _multipart(self, path: str, filename: str, content: bytes, content_type: str):
        boundary = "----reavectors" + str(int(time.time() * 1000))
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        body = head + content + tail
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }
        status, data = self._transport("POST", f"{self.base}{path}", headers, body, self.timeout)
        if status == 401:
            raise TripoAuthError(data.get("message") or "unauthorized")
        if status >= 400:
            raise TripoError(f"HTTP {status}: {data.get('message', data)}")
        return data

    # ---- public API -----------------------------------------------------
    def upload_image(self, data: bytes, filename: str = "input.png",
                     content_type: str = "image/png") -> str:
        """Upload a source image (free) and return its file token."""
        resp = self._multipart("/upload", filename, data, content_type)
        token = (resp.get("data") or {}).get("image_token") or (resp.get("data") or {}).get("file_token")
        if not token:
            raise TripoError(f"upload did not return a token: {resp}")
        return token

    def create_image_to_model(self, file_token: str, texture: bool = True, pbr: bool = True) -> str:
        payload = {
            "type": "image_to_model",
            "file": {"type": "png", "file_token": file_token},
            "model_version": self.model_version,
            "texture": texture, "pbr": pbr, "texture_quality": self.texture_quality,
        }
        resp = self._json("POST", "/generation/image-to-model", payload)
        task_id = (resp.get("data") or {}).get("task_id")
        if not task_id:
            raise TripoError(f"task creation did not return a task_id: {resp}")
        return task_id

    def get_task(self, task_id: str) -> dict:
        return self._json("GET", f"/generation/{task_id}")

    def wait(self, task_id: str, poll_seconds: float = 5.0, timeout: float = 900.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            resp = self.get_task(task_id)
            data = resp.get("data") or {}
            status = (data.get("status") or "").lower()
            if status in ("success", "succeeded"):
                return data
            if status in ("failed", "banned", "expired", "cancelled"):
                raise TripoError(f"task {task_id} {status}: {data.get('message', '')}")
            if time.monotonic() > deadline:
                raise TripoError(f"task {task_id} timed out (last status: {status})")
            time.sleep(poll_seconds)


def check_cost(estimated_usd: float = None) -> None:
    """Per-job cost guard. Raises TripoError if the configured ceiling is exceeded."""
    est = 0.30 if estimated_usd is None else estimated_usd
    if est > config.AI_TRIPO_MAX_USD_PER_JOB:
        raise TripoError(
            f"estimated Tripo cost ~${est:.2f} exceeds AI_TRIPO_MAX_USD_PER_JOB "
            f"(${config.AI_TRIPO_MAX_USD_PER_JOB:.2f})")


def enabled() -> bool:
    return config.AI_ENABLE_TRIPO and bool(config.AI_TRIPO_API_KEY)
