"""
Stable Fast 3D (SF3D) adapter. Runs ONLY on the GPU worker.

Model: ``stabilityai/stable-fast-3d`` (Stability AI).
LICENCE: **Stability AI Community License** - free for personal and for commercial
use *below* USD 1M annual revenue; above that an enterprise licence is required.
Contrast with TripoSR, which is **MIT** (fully permissive). Default production
model is therefore TripoSR; SF3D is opt-in (``AI_3D_MODEL=sf3d``).

VERIFY: not executed here (no GPU in this environment). Confirm with the worker
smoke test (``infra/aws/install-triposr.sh`` / bench harness) before enabling.

Install (worker only): see infra/aws/requirements-worker.txt
"""

from __future__ import annotations

import os


class SF3DAdapter:
    name = "sf3d"
    vram_gb = 6.5
    license = "Stability AI Community License (commercial < $1M revenue)"  # noqa: A003

    def __init__(self, cache_dir: str = "./models", repo_dir: str = None):
        self.cache_dir = cache_dir
        self.repo_dir = repo_dir or os.environ.get("SF3D_REPO", "/opt/stable-fast-3d")
        self.model = None

    def load(self) -> None:
        import torch
        from sf3d.system import SF3D  # provided by the Stability SF3D repo

        self.model = SF3D.from_pretrained(
            "stabilityai/stable-fast-3d",
            config_name="config.yaml",
            weight_name="model.safetensors",
        )
        self.model.to("cuda" if torch.cuda.is_available() else "cpu")

    def unload(self) -> None:
        self.model = None

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        import torch
        from PIL import Image

        os.makedirs(out_dir, exist_ok=True)
        image = Image.open(input_path).convert("RGBA")
        try:
            from rembg import remove
            image = remove(image)
        except Exception:  # noqa: BLE001 - optional
            pass
        image = image.convert("RGB")

        with torch.no_grad():
            mesh = self.model.run_image(
                image,
                bake_resolution=int(params.get("bake_resolution", 1024)),
                remesh=params.get("remesh", "none"),
            )
        glb_path = os.path.join(out_dir, "model.glb")
        mesh.export(glb_path)
        return glb_path
