"""
Dual-GPU scheduler (Kaggle T4 x2).

Rules (per your architecture):
  * GPU 0 -> images / LoRA / textures,  GPU 1 -> video / 3D   (configurable).
  * One job per GPU at a time (a lock per GPU) -> no VRAM exhaustion.
  * VRAM guard: a model that needs more than a GPU has is refused up-front.
  * Model caching: one manager per GPU; unload releases VRAM.
  * The two GPUs are independent 14.56 GB pools, never a 29 GB pool.

In-process ``run()`` is for *sequential* orchestration (one notebook cell at a
time). For genuinely parallel use of both GPUs, launch one process per GPU with
``CUDA_VISIBLE_DEVICES`` (see ``scripts/gpu_job.py``) because the torch device is
process-wide.

No torch import here.
"""

from __future__ import annotations

import threading

from .registry import get as get_spec

DEFAULT_TASK_GPU = {
    "text2image": "0", "image_edit": "0", "lora": "0", "texture": "0",
    "image2video": "1", "text2video": "1", "image2_3d": "1",
}
T4_VRAM_GB = 14.56


class VramError(RuntimeError):
    pass


class DualGPUScheduler:
    def __init__(self, usable_vram=None, task_gpu=None, manager_factory=None):
        self.usable = dict(usable_vram or {"0": T4_VRAM_GB, "1": T4_VRAM_GB})
        self.task_gpu = {**DEFAULT_TASK_GPU, **(task_gpu or {})}
        self._locks = {g: threading.Lock() for g in self.usable}
        self._managers = {}
        self._factory = manager_factory or self._default_factory

    # -- placement ---------------------------------------------------------
    def gpu_for(self, model_id: str) -> str:
        spec = get_spec(model_id)
        g = self.task_gpu.get(spec.task)
        if g in self.usable:
            return g
        if spec.gpu in self.usable:
            return spec.gpu
        return next(iter(self.usable))

    def check(self, model_id: str, gpu: str) -> None:
        spec = get_spec(model_id)
        if gpu not in self.usable:
            raise KeyError(f"unknown gpu {gpu}")
        if spec.vram_gb > self.usable[gpu]:
            raise VramError(
                f"{spec.id} needs ~{spec.vram_gb} GB but GPU {gpu} has "
                f"{self.usable[gpu]} GB. Not usable on a T4.")

    # -- managers ----------------------------------------------------------
    @staticmethod
    def _default_factory(_gpu: str):
        from .worker_models import build_default_manager
        return build_default_manager()

    def manager(self, gpu: str):
        if gpu not in self._managers:
            self._managers[gpu] = self._factory(gpu)
        return self._managers[gpu]

    # -- run ---------------------------------------------------------------
    def run(self, model_id: str, input_path: str, params: dict = None,
            out_dir: str = ".", gpu: str = None) -> str:
        spec = get_spec(model_id)
        if not spec.adapter or spec.status != "adapter_live":
            raise RuntimeError(f"{spec.id} has no live adapter yet (planned)")
        gpu = gpu or self.gpu_for(model_id)
        self.check(model_id, gpu)
        p = dict(params or {})
        p.setdefault("device", f"cuda:{gpu}")   # best-effort hint for adapters
        with self._locks[gpu]:
            return self.manager(gpu).run(spec.adapter, input_path, p, out_dir)

    def unload(self, gpu: str = None) -> None:
        for g in ([gpu] if gpu else list(self._managers)):
            mgr = self._managers.pop(g, None)
            if mgr is not None:
                try:
                    mgr.unload()
                except Exception:  # noqa: BLE001
                    pass

    def status(self) -> dict:
        return {g: {"busy": lock.locked(), "vram_gb": self.usable[g]}
                for g, lock in self._locks.items()}