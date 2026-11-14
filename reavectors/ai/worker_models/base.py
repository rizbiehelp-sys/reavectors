"""
Worker-side model adapters + a VRAM-aware model manager.

These modules run **only on the GPU worker** (they import torch/CUDA). They are
never imported on the control plane. Selecting a model is by name; the manager
loads one model at a time and frees VRAM between models so a 16 GB T4 is enough.

Verified choice: **TripoSR** (VAST-AI-Research / Stability AI), released under the
**MIT** licence (code + weights + demo), ~6 GB VRAM, single-image -> mesh, optional
texture baking. Alternatives (Hunyuan3D-2.1, TRELLIS, LGM) are noted in
docs/MODEL_LICENSES.md; TRELLIS needs Ampere+ (flash-attn) so it cannot run on a T4.
"""

from __future__ import annotations

import gc
from typing import Callable, Protocol


class ModelAdapter(Protocol):
    name: str
    vram_gb: float

    def load(self) -> None: ...
    def unload(self) -> None: ...
    def run(self, input_path: str, params: dict, out_dir: str) -> str: ...   # -> output path


def free_vram_gb() -> float:
    """Best-effort free VRAM in GB (0 if torch/CUDA unavailable)."""
    try:
        import torch  # noqa: F401
        if not torch.cuda.is_available():
            return 0.0
        free_b, _total = torch.cuda.mem_get_info()
        return free_b / (1024 ** 3)
    except Exception:  # noqa: BLE001
        return 0.0


class ModelManager:
    """
    Loads at most one adapter at a time, unloading the previous one first.

    Rationale: the T4 has ~16 GB; loading image + video + 3D models together would
    OOM. We unload the current model, empty the CUDA cache, then load the next.
    """

    def __init__(self, builders: "dict[str, Callable[[], ModelAdapter]]"):
        self._builders = builders
        self._adapter: "ModelAdapter | None" = None

    @property
    def current(self) -> "str | None":
        return self._adapter.name if self._adapter else None

    def unload(self) -> None:
        if self._adapter is not None:
            try:
                self._adapter.unload()
            finally:
                self._adapter = None
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass

    def ensure(self, name: str) -> ModelAdapter:
        """Return the loaded adapter for ``name``, loading it if needed."""
        if name not in self._builders:
            raise KeyError(f"unknown model adapter: {name}")
        if self._adapter is not None and self._adapter.name == name:
            return self._adapter
        self.unload()
        adapter = self._builders[name]()
        need = adapter.vram_gb
        have = free_vram_gb()
        if have and have < need:
            raise RuntimeError(f"{name} needs ~{need} GB VRAM but only {have:.1f} GB is free")
        adapter.load()
        self._adapter = adapter
        return adapter

    def run(self, name: str, input_path: str, params: dict, out_dir: str) -> str:
        return self.ensure(name).run(input_path, params, out_dir)


def build_default_manager(cache_dir: str = "./models") -> ModelManager:
    """
    Register the available adapters (imported lazily so torch isn't needed here).

    Default production model is ``triposr`` (MIT, fully free). ``sf3d`` is opt-in:
    higher detail but under the Stability AI Community License (commercial only
    below $1M revenue). The same adapters run unchanged on Kaggle and AWS.
    """
    from .triposr import TripoSRAdapter

    def _sf3d():
        from .sf3d import SF3DAdapter
        return SF3DAdapter(cache_dir=cache_dir)

    def _hunyuan():
        from .hunyuan3d import Hunyuan3DAdapter
        return Hunyuan3DAdapter(cache_dir=cache_dir)

    def _hunyuan_mini():
        from .hunyuan3d import Hunyuan3DMiniAdapter
        return Hunyuan3DMiniAdapter(cache_dir=cache_dir)

    return ModelManager({
        "triposr": lambda: TripoSRAdapter(cache_dir=cache_dir),          # ~6 GB
        "sf3d": _sf3d,                                                   # ~6.5 GB  (default)
        "hunyuan3d-mini": _hunyuan_mini,                                 # ~10 GB   fits T4
        "hunyuan3d": _hunyuan,                                           # ~24 GB   g5/g6 only
    })
