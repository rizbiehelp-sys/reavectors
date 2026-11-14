"""
Tripo hosted image->3D adapter (PAID; opt-in, OFF by default).

Wraps the **official `tripo3d` SDK** (verified base `https://openapi.tripo3d.ai`,
routes `/v3/files`, `/v3/generation/image-to-model`, `/v3/tasks/{id}`). Using the
SDK avoids hand-rolling an API that can change.

Auth: requires the **secret** key (`tsk_...`). A client id (`tcli_...`) does NOT
authenticate the OpenAPI and is rejected up front.

Cost: Tripo is 1 credit = $0.01 USD; image->3D is ~20-30 credits (~$0.20-$0.30)
per model. `check_cost` guards per-job spend, and an empty balance surfaces as a
clear `TripoCreditError` (nothing is charged on rejection).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from .. import config


class TripoError(RuntimeError):
    pass


class TripoAuthError(TripoError):
    pass


class TripoCreditError(TripoError):
    pass


def enabled() -> bool:
    return bool(config.AI_ENABLE_TRIPO and config.AI_TRIPO_API_KEY)


def _require_key() -> None:
    key = config.AI_TRIPO_API_KEY
    if not key:
        raise TripoAuthError("AI_TRIPO_API_KEY is not set")
    if not key.startswith("tsk_"):
        raise TripoAuthError(
            "Tripo needs the SECRET key (tsk_...). A client id (tcli_...) does not "
            "authenticate the OpenAPI.")


def check_cost(estimated_usd: float = None) -> None:
    est = 0.30 if estimated_usd is None else estimated_usd
    if est > config.AI_TRIPO_MAX_USD_PER_JOB:
        raise TripoError(
            f"estimated Tripo cost ~${est:.2f} exceeds AI_TRIPO_MAX_USD_PER_JOB "
            f"(${config.AI_TRIPO_MAX_USD_PER_JOB:.2f})")


def _sdk():
    try:
        import tripo3d  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise TripoError("the 'tripo3d' package is not installed") from exc
    return tripo3d


def balance() -> dict:
    """Return the account balance (free; used by admin/capacity)."""
    _require_key()
    tripo3d = _sdk()

    async def _run():
        async with tripo3d.TripoClient(api_key=config.AI_TRIPO_API_KEY) as client:
            b = await client.get_balance()
            return getattr(b, "balance", b)

    try:
        return {"ok": True, "balance": asyncio.run(_run())}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _classify(exc)}


def generate_glb(image_bytes: bytes, filename: str = "input.png", *,
                 model_version: str = None, texture: bool = True, pbr: bool = True,
                 quad: bool = False, face_limit: int = None, texture_quality: str = None,
                 poll_seconds: float = 5.0, timeout: float = None,
                 _client_factory=None) -> dict:
    """
    Image bytes -> textured GLB bytes. Blocking; call from a worker thread.

    Returns ``{"glb": bytes, "task_id": str, "files": {type: name}}``.
    ``_client_factory`` is a test seam (a callable returning an async context
    manager exposing the tripo3d client API).
    """
    _require_key()
    check_cost()
    tripo3d = _sdk()
    factory = _client_factory or (lambda: tripo3d.TripoClient(api_key=config.AI_TRIPO_API_KEY))
    timeout = timeout or config.AI_IMAGE_3D_JOB_TIMEOUT_SECONDS

    async def _run():
        async with factory() as client:
            with tempfile.TemporaryDirectory(prefix="tripo_") as td:
                src = os.path.join(td, filename)
                with open(src, "wb") as fh:
                    fh.write(image_bytes)
                task_id = await client.image_to_model(
                    image=src,
                    model_version=model_version or config.AI_TRIPO_MODEL,
                    texture=texture, pbr=pbr, quad=quad, face_limit=face_limit,
                    texture_quality=texture_quality or config.AI_TRIPO_TEXTURE_QUALITY,
                )
                task = await client.wait_for_task(task_id, polling_interval=poll_seconds, timeout=timeout)
                status = str(getattr(task.status, "value", task.status)).lower()
                if status not in ("success", "succeeded"):
                    raise TripoError(f"tripo task {status}")
                files = await client.download_task_models(task, td)
                path = files.get("pbr_model") or files.get("model") \
                    or next((v for v in files.values() if v), None)
                if not path or not os.path.exists(path):
                    raise TripoError(f"tripo returned no model file ({list(files)})")
                with open(path, "rb") as fh:
                    data = fh.read()
                return {"glb": data, "task_id": task_id,
                        "files": {k: os.path.basename(v) for k, v in files.items() if v}}

    try:
        return asyncio.run(_run())
    except TripoError:
        raise
    except Exception as exc:  # noqa: BLE001 - classify upstream APIs errors
        raise TripoError(_classify(exc)) from exc


def _classify(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "credit" in low or "2010" in msg:
        return "Tripo account has insufficient credits - purchase credits to generate 3D."
    if "401" in msg or "auth" in low or "api key" in low:
        return f"Tripo authentication failed: {msg}"
    return f"{type(exc).__name__}: {msg}"
