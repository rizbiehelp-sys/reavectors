"""
Cloudflare Workers AI adapter (optional live image API).

Uses the free daily Neuron allowance only. Disabled unless AI_CF_ACCOUNT_ID and
AI_CF_API_TOKEN are set. Never enables paid usage, never retries into billing.

Endpoint: POST https://api.cloudflare.com/client/v4/accounts/{id}/ai/run/{model}
Model default: @cf/black-forest-labs/flux-2-klein-4b (verify current id).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from .. import config


class CloudflareUnavailable(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.AI_CF_ACCOUNT_ID and config.AI_CF_API_TOKEN)


class CloudflareAI:
    def __init__(self, account_id: str = None, token: str = None, model: str = None,
                 transport=None, timeout: int = 90):
        self.account_id = account_id or config.AI_CF_ACCOUNT_ID
        self.token = token or config.AI_CF_API_TOKEN
        self.model = model or config.AI_CF_IMAGE_MODEL
        self.timeout = timeout
        self._transport = transport or self._http
        if not (self.account_id and self.token):
            raise CloudflareUnavailable("Cloudflare AI not configured (AI_CF_ACCOUNT_ID/AI_CF_API_TOKEN)")

    def _http(self, url, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.getcode(), r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise CloudflareUnavailable(f"network: {exc.reason}") from exc

    def text_to_image(self, prompt: str, steps: int = 4) -> bytes:
        url = (f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
               f"/ai/run/{self.model}")
        code, body = self._transport(url, {"prompt": prompt[:2048], "num_steps": int(steps)})
        if code >= 300:
            raise CloudflareUnavailable(f"[{code}] {body[:200]!r}")
        # Responses may be a JSON {result:{image: b64}} or raw image bytes
        try:
            data = json.loads(body)
            img = data.get("result", {}).get("image")
            if img:
                return base64.b64decode(img)
        except Exception:  # noqa: BLE001
            pass
        if body[:8] == b"\x89PNG\r\n\x1a\n" or body[:3] == b"\xff\xd8\xff":
            return body
        raise CloudflareUnavailable("unexpected response shape from Workers AI")