"""
3D AI Studio hosted client (Tencent Hunyuan 3D Pro/Rapid).

This is an OPT-IN, PAID hosted service (credits). It is **off by default**
(``AI_ENABLE_3DAS=0``) and never runs unless an API key is configured. It is the
fastest way to test true AI reconstruction without your own GPU worker.

Contract (from 3daistudio.com API docs):
  POST {base}/v1/3d-models/tencent/generate/pro/    -> {"task_id","created_at"}
       Authorization: Bearer <key>; body: model, prompt|image(base64), enable_pbr,
       face_count, generate_type, polygon_type, multi_view_images[]
  GET  {base}/v1/generation-request/<task_id>/status/
       -> {"status","progress","failure_reason","results":[{"asset","asset_type"}]}
  Pro output = GLB (asset_type "3D_MODEL"); Rapid = ZIP/OBJ ("ARCHIVE").
  Costs: Pro 60 credits (+20 PBR, +20 multi-view); Rapid 35 (+20 PBR).
"""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
import urllib.error


class ThreeDAIStudioError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class ThreeDAIStudioClient:
    def __init__(self, api_key: str, base: str = "https://api.3daistudio.com",
                 timeout: int = 30, transport=None):
        self.api_key = api_key
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._transport = transport or self._http

    # -- transport (injectable for tests) ----------------------------------
    def _http(self, method: str, url: str, payload: dict):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.getcode(), json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(body).get("detail") or json.loads(body).get("error") or body
            except Exception:  # noqa: BLE001
                detail = body
            raise ThreeDAIStudioError(exc.code, str(detail)) from exc
        except urllib.error.URLError as exc:
            raise ThreeDAIStudioError(0, f"network error: {exc.reason}") from exc

    # -- API ---------------------------------------------------------------
    def submit_pro(self, image: str = None, prompt: str = None, model: str = "3.1",
                   enable_pbr: bool = True, face_count: int = 500_000,
                   generate_type: str = "Normal", polygon_type: str = None,
                   multi_view: list = None) -> dict:
        if not image and not prompt and not multi_view:
            raise ThreeDAIStudioError(400, "provide an image, a prompt, or multi_view images")
        payload = {"model": model, "enable_pbr": bool(enable_pbr),
                   "face_count": int(face_count), "generate_type": generate_type or "Normal"}
        if multi_view:
            payload["multi_view_images"] = multi_view      # image must NOT also be sent
        elif image:
            payload["image"] = image
        if prompt:
            payload["prompt"] = prompt[:1024]
        if polygon_type:
            payload["polygon_type"] = polygon_type
        status, body = self._transport("POST", f"{self.base}/v1/3d-models/tencent/generate/pro/", payload)
        if status >= 400 or "task_id" not in body:
            raise ThreeDAIStudioError(status, body.get("detail", "submit failed") if isinstance(body, dict) else "submit failed")
        return body

    def status(self, task_id: str) -> dict:
        tid = urllib.parse.quote(task_id, safe="")
        status, body = self._transport("GET", f"{self.base}/v1/generation-request/{tid}/status/", None)
        if status >= 400:
            raise ThreeDAIStudioError(status, "status failed")
        return body

    @staticmethod
    def credits(model: str = "3.1", enable_pbr: bool = True, multi_view: bool = False) -> int:
        base = 60
        if enable_pbr:
            base += 20
        if multi_view:
            base += 20
        return base
