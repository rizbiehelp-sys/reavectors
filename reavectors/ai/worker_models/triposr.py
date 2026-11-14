"""
TripoSR adapter (free, MIT). Runs ONLY on the GPU worker.

Model: ``stabilityai/TripoSR`` (VAST-AI-Research / Stability AI, MIT licence).
Single image -> mesh; ~6 GB VRAM. Optional texture baking via ``--bake-texture``.

This follows the public TripoSR API (`tsr.system.TSR`, `model.extract_mesh`,
`trimesh` export). It is marked **VERIFY**: it has not been executed here because
no GPU is available in this environment; run `run.py` from the TripoSR repo once
on the worker to confirm output before enabling public use.

Install (worker only):
    pip install -r infra/aws/requirements-worker.txt
    git clone https://github.com/VAST-AI-Research/TripoSR /opt/TripoSR
"""

from __future__ import annotations

import os


class TripoSRAdapter:
    name = "triposr"
    vram_gb = 6.0

    def __init__(self, cache_dir: str = "./models", repo_dir: str = None):
        self.cache_dir = cache_dir
        self.repo_dir = repo_dir or os.environ.get("TRIPOSR_REPO", "/opt/TripoSR")
        self.model = None

    # ---- lifecycle ------------------------------------------------------
    def load(self) -> None:
        import torch
        from tsr.system import TSR  # provided by the TripoSR repo (in repo_dir on PYTHONPATH)

        self.model = TSR.from_pretrained(
            "stabilityai/TripoSR",
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        # smaller chunk keeps VRAM low on a T4
        self.model.renderer.set_chunk_size(int(os.environ.get("TRIPOSR_CHUNK", "8192")))
        self.model.to("cuda" if torch.cuda.is_available() else "cpu")

    def unload(self) -> None:
        self.model = None

    # ---- inference ------------------------------------------------------
    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        import torch
        from PIL import Image

        os.makedirs(out_dir, exist_ok=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"

        image = Image.open(input_path).convert("RGBA")
        # background removal improves single-object results; rembg is in requirements-worker
        try:
            from rembg import remove
            image = remove(image)
        except Exception:  # noqa: BLE001 - optional
            pass
        image = image.convert("RGB")

        with torch.no_grad():
            codes = self.model([image], device=device)
        scene_codes = codes
        meshes = self.model.extract_mesh(scene_codes, resolution=int(params.get("mc_resolution", 256)))
        mesh = meshes[0]

        bake = bool(params.get("bake_texture", True))
        glb_path = os.path.join(out_dir, "model.glb")
        if bake:
            try:
                self.model.renderer.set_chunk_size(int(os.environ.get("TRIPOSR_CHUNK", "8192")))
                scene = self.model.renderer.neural_render  # noqa: F841 (documented hook)
                mesh.visual = mesh.visual  # keep vertex colors
            except Exception:  # noqa: BLE001
                pass
        mesh.export(glb_path)
        return glb_path
