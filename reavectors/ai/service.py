"""
AI Studio service layer — the endpoints, wired to the store + GPU manager.

No web-framework types here: methods return ``(http_status, payload_dict)`` and
the existing stdlib ``server.Handler`` just serialises them. Fully usable without
AWS (mock provider) and unit-testable directly.
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import time

from .. import config
from . import catalog, limits, tripo
from .lifecycle import GPUManager, PENDING_STATES
from .models import JobType, ValidationError, validate_request
from .providers import MockGPUProvider
from .store import JobStore

# deadline per job type (seconds)
_DEADLINE = {
    JobType.TEXT_TO_IMAGE: config.AI_IMAGE_INFERENCE_TIMEOUT_SECONDS,
    JobType.IMAGE_TO_VIDEO: config.AI_VIDEO_JOB_TIMEOUT_SECONDS,
    JobType.TEXT_TO_VIDEO: config.AI_VIDEO_JOB_TIMEOUT_SECONDS,
    JobType.IMAGE_TO_3D: config.AI_IMAGE_3D_JOB_TIMEOUT_SECONDS,
}

MAX_LORA_BYTES = config.AI_MAX_LORA_BYTES


class AIService:
    def __init__(self, store: JobStore, manager: GPUManager, clock=time.time):
        self.store = store
        self.manager = manager
        self.clock = clock
        self.limiter = limits.RateLimiter(config.AI_RATE_REQUESTS_PER_MINUTE, 60.0, clock)
        self._thread = None
        self._stop = threading.Event()

    # ---- background pump ------------------------------------------------
    def start_background(self, interval: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while not self._stop.wait(interval):
                try:
                    self.manager.pump()
                except Exception:  # noqa: BLE001 - never kill the pump
                    pass

        self._thread = threading.Thread(target=loop, daemon=True, name="ai-pump")
        self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _public(job: dict) -> dict:
        return {
            "job_id": job["id"],
            "type": job["type"],
            "state": job["state"],
            "model": job.get("model"),
            "created": job.get("created"),
            "deadline": job.get("deadline"),
            "result_url": job.get("result_url"),
            "error": job.get("error"),
            "gpu_seconds": job.get("gpu_seconds"),
            "provider": job.get("provider"),
        }

    # ---- endpoints ------------------------------------------------------
    def submit(self, user_id: str, body: dict, idem_key: str = None):
        try:
            job_type = validate_request(body.get("type"), body.get("params") or {})
        except ValidationError as exc:
            return 422, {"error": str(exc)}

        try:
            limits.check_submit(self.store, user_id, job_type, self.limiter)
        except limits.LimitError as exc:
            return exc.status, {"error": exc.message}

        model = (body.get("params") or {}).get("model") or f"{job_type.value}-default"
        job = self.store.create_job(
            user_id, job_type.value, model, body.get("params") or {},
            idem_key=idem_key, deadline_seconds=_DEADLINE[job_type])

        # Only kick the GPU for a genuinely new job (idempotent replays don't).
        if job["state"] == "created":
            self.manager.kick(job)
            job = self.store.get_job(job["id"])

        depth = self.store.count_by_state(PENDING_STATES)
        return 202, {
            "job_id": job["id"],
            "state": job["state"],
            "type": job["type"],
            "queue_position": depth if job["state"] in PENDING_STATES else 0,
            "eta_hint": "first request may take a few minutes while the GPU wakes",
        }

    def get(self, user_id: str, job_id: str, admin: bool = False):
        job = self.store.get_job(job_id)
        if not job or (job["user_id"] != user_id and not admin):
            return 404, {"error": "job not found"}
        out = self._public(job)
        out["queue_position"] = self.store.count_by_state(PENDING_STATES)
        return 200, out

    def cancel(self, user_id: str, job_id: str):
        job = self.store.get_job(job_id)
        if not job or job["user_id"] != user_id:
            return 404, {"error": "job not found"}
        if job["state"] in ("succeeded", "failed", "cancelled", "timed_out"):
            return 409, {"error": f"cannot cancel a {job['state']} job"}
        self.store.set_state(job_id, "cancelled")
        return 200, {"job_id": job_id, "state": "cancelled"}

    def history(self, user_id: str, limit: int = 50):
        return 200, {"jobs": [self._public(j) for j in self.store.list_jobs(user_id, limit)]}

    def capacity(self):
        status = self.manager.status()
        status.update({
            "queue_depth": self.store.count_by_state(PENDING_STATES),
            "running": self.store.running_count(),
            "max_queue": config.AI_MAX_GLOBAL_QUEUE,
            "max_active_jobs": self.store and config.AI_MAX_GPU_ACTIVE_JOBS,
            "budget": limits.budget_status(self.store, self.clock),
            "fallback_enabled": config.AI_USE_API_FALLBACK,
        })
        return 200, status

    def models(self):
        return 200, {"models": catalog.models_for(), "enabled": [m["id"] for m in catalog.enabled_models()]}

    def loras(self, user_id: str):
        builtin = catalog.builtin_loras()
        mine = [l for l in self.store.list_loras(user_id) if l["user_id"]]
        return 200, {"builtin": builtin, "user": mine}

    def upload_lora(self, user_id: str, filename: str, params: dict, data: bytes):
        if not filename.lower().endswith(".safetensors"):
            return 415, {"error": "only .safetensors LoRA files are accepted"}
        if len(data) > MAX_LORA_BYTES:
            return 413, {"error": "LoRA file too large"}
        ok, meta_or_err = _inspect_safetensors(data)
        if not ok:
            return 415, {"error": meta_or_err}
        # storage adapter (local dev: discarded; prod: private S3) — metadata only here
        lora = self.store.add_lora(
            user_id=user_id, name=params.get("name") or filename,
            base=params.get("base"), trigger=params.get("trigger"),
            weight=float(params.get("weight") or 0.8),
            license=params.get("license"), source_url=params.get("source_url"),
            checksum=meta_or_err.get("checksum"), size=len(data))
        return 201, {"lora": lora, "meta": meta_or_err}

    def delete_lora(self, user_id: str, lora_id: str):
        if self.store.delete_lora(lora_id, user_id):
            return 200, {"deleted": lora_id}
        return 404, {"error": "lora not found"}

    # ---- AI image -> 3D (Tripo hosted; paid, opt-in) --------------------
    def _obj_dir(self, user_id: str, kind: str) -> str:
        base = os.path.join(os.path.dirname(os.path.abspath(config.AI_JOB_DB_PATH)) or ".", "objects")
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", user_id)[:64] or "anon"
        path = os.path.join(base, "users", safe, kind)
        os.makedirs(path, exist_ok=True)
        return path

    def submit_3d(self, user_id: str, image_bytes: bytes, filename: str, params: dict):
        from ..security import validate_image
        _fmt, reason = validate_image(image_bytes)
        if reason:
            return 415, {"error": reason}
        if not tripo.enabled():
            return 503, {"error": "AI 3D is not enabled. Add Tripo credits (AI_TRIPO_API_KEY) "
                                  "or connect the GPU worker (TripoSR)."}
        try:
            limits.check_submit(self.store, user_id, JobType.IMAGE_TO_3D, self.limiter)
        except limits.LimitError as exc:
            return exc.status, {"error": exc.message}

        job = self.store.create_job(
            user_id, JobType.IMAGE_TO_3D.value, config.AI_TRIPO_MODEL,
            {"filename": filename, "provider": "tripo"},
            deadline_seconds=config.AI_IMAGE_3D_JOB_TIMEOUT_SECONDS)
        in_path = os.path.join(self._obj_dir(user_id, "inputs"), f"{job['id']}.png")
        with open(in_path, "wb") as fh:
            fh.write(image_bytes)
        threading.Thread(target=self._run_3d, args=(job["id"], user_id, in_path),
                         daemon=True, name="ai-3d").start()
        return 202, {"job_id": job["id"], "state": "queued", "provider": "tripo",
                     "eta_hint": "image-to-3D usually takes 30-120 seconds"}

    def _run_3d(self, job_id: str, user_id: str, in_path: str) -> None:
        self.store.set_state(job_id, "running", provider="tripo")
        try:
            with open(in_path, "rb") as fh:
                data = fh.read()
            res = tripo.generate_glb(data, os.path.basename(in_path))
            out_path = os.path.join(self._obj_dir(user_id, "models"), f"{job_id}.glb")
            with open(out_path, "wb") as fh:
                fh.write(res["glb"])
            self.store.set_state(job_id, "succeeded",
                                 result_url=f"/api/ai/jobs/{job_id}/result", provider="tripo")
        except tripo.TripoError as exc:
            self.store.set_state(job_id, "failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            self.store.set_state(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            try:
                os.remove(in_path)
            except OSError:
                pass

    # ---- Product photo -> 3D (parametric, CPU, label-accurate) ----------
    def product3d(self, user_id: str, image_bytes: bytes, label_bytes: bytes = None,
                  quad=None, material: str = "auto", mode: str = "single"):
        from ..security import validate_image
        _fmt, reason = validate_image(image_bytes)
        if reason:
            return 415, {"error": reason}
        from . import product3d as p3d
        try:
            spec = p3d.analyze_product(image_bytes, label_bytes=label_bytes,
                                       quad=quad, material=material, mode=mode)
        except ValueError as exc:
            return 422, {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return 500, {"error": f"{type(exc).__name__}: {exc}"}
        return 200, spec

    def result_file(self, job_id: str, user_id: str):
        """Return (path, None) for the caller's GLB result, or (None, error)."""
        job = self.store.get_job(job_id)
        if not job or job["user_id"] != user_id:
            return None, "job not found"
        if job["state"] != "succeeded":
            return None, f"job is {job['state']}"
        path = os.path.join(self._obj_dir(user_id, "models"), f"{job_id}.glb")
        if not os.path.isfile(path):
            return None, "result file missing"
        return path, None

    def tripo_balance(self):
        if not config.AI_TRIPO_API_KEY:
            return 200, {"ok": False, "error": "AI_TRIPO_API_KEY not set"}
        return 200, tripo.balance()


def _inspect_safetensors(data: bytes):
    """
    Validate the safetensors header **without executing anything**.

    Format: u64 LE header length, then a JSON header. We only parse the JSON to
    confirm structure (and pull a checksum); we never load tensors or code.
    """
    import hashlib
    if len(data) < 8:
        return False, "not a valid safetensors file (too short)"
    (n,) = struct.unpack("<Q", data[:8])
    if n <= 0 or n > 100 * 1024 * 1024 or 8 + n > len(data):
        return False, "invalid safetensors header length"
    try:
        header = json.loads(data[8:8 + n].decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False, "safetensors header is not valid JSON"
    if not isinstance(header, dict):
        return False, "safetensors header must be an object"
    tensors = [k for k in header if k != "__metadata__"]
    if not tensors:
        return False, "safetensors header contains no tensors"
    return True, {"tensors": len(tensors), "checksum": hashlib.sha256(data).hexdigest()}


# ---------------------------------------------------------------------------
# process-wide singleton
# ---------------------------------------------------------------------------
_service = None
_service_lock = threading.Lock()


def get_service() -> AIService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            store = JobStore(config.AI_JOB_DB_PATH)
            manager = GPUManager(MockGPUProvider(), store)
            _service = AIService(store, manager)
            if config.AI_ENABLED:
                _service.start_background()
    return _service
