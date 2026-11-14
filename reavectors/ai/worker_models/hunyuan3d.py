"""
Hunyuan3D-2.1 adapter (opt-in, higher quality). Runs ONLY on the GPU worker.

Model: ``tencent/Hunyuan3D-2.1`` (shape DiT + paint/texture pipeline).
LICENCE: **Tencent Hunyuan 3D 2.1 Community License** - free for personal and
commercial use below 100M monthly active users **and** in permitted territories
(verify EU/UK/KR exclusions before public use). Not MIT.

VRAM: the full 2.1 pipeline needs ~24 GB. It does **not** fit a 16 GB T4, so it
requires a larger worker (e.g. AWS ``g5.xlarge`` A10G 24 GB or ``g6.xlarge`` L4)
or the lighter ``tencent/Hunyuan3D-2mini`` on a T4. Default production model is
still **TripoSR** (MIT, ~6 GB, fits a T4); Hunyuan3D is the quality upgrade.

VERIFY: not executed here (no GPU in this environment). Confirm with the bench
harness / worker smoke test before enabling.

Install (worker only):
    git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1 /opt/Hunyuan3D-2.1
    pip install -r /opt/Hunyuan3D-2.1/requirements.txt   # + texture: hy3dgen
"""

from __future__ import annotations

import os


class Hunyuan3DAdapter:
    name = "hunyuan3d"
    vram_gb = 24.0
    license = "Tencent Hunyuan 3D 2.1 Community License"  # noqa: A003

    def __init__(self, cache_dir: str = "./models", repo_dir: str = None,
                 variant: str = "tencent/Hunyuan3D-2.1"):
        self.cache_dir = cache_dir
        self.repo_dir = repo_dir or os.environ.get("HUNYUAN3D_REPO", "/opt/Hunyuan3D-2.1")
        self.variant = os.environ.get("HUNYUAN3D_VARIANT", variant)
        self.shape = None
        self.paint = None

    def load(self) -> None:
        import torch
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
        from hy3dgen.texgen import Hunyuan3DPaintPipeline

        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(self.variant)
        # texture stage is optional but gives the "looks real" result
        self.paint = Hunyuan3DPaintPipeline.from_pretrained(self.variant)
        if device == "cpu":
            self.shape.to("cpu")
        else:
            self.shape.enable_model_cpu_offload()

    def unload(self) -> None:
        self.shape = None
        self.paint = None

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        from PIL import Image

        os.makedirs(out_dir, exist_ok=True)
        image = Image.open(input_path).convert("RGBA")
        try:
            from rembg import remove
            image = remove(image)
        except Exception:  # noqa: BLE001 - optional
            pass
        image = image.convert("RGB")

        mesh = self.shape(image=image,
                          num_inference_steps=int(params.get("steps", 30)),
                          octree_resolution=int(params.get("octree", 256)))[0]
        if bool(params.get("bake_texture", True)) and self.paint is not None:
            mesh = self.paint(mesh, image=image)
        glb_path = os.path.join(out_dir, "model.glb")
        mesh.export(glb_path)
        return glb_path


class Hunyuan3DMiniAdapter(Hunyuan3DAdapter):
    """
    Hunyuan3D-2mini — the variant that FITS a 16 GB T4 (~10 GB). Best free
    quality we can run on the free-credit g4dn.xlarge. Same Community Licence.
    """
    name = "hunyuan3d-mini"
    vram_gb = 10.0

    def __init__(self, cache_dir: str = "./models", repo_dir: str = None):
        super().__init__(cache_dir=cache_dir, repo_dir=repo_dir,
                         variant="tencent/Hunyuan3D-2mini")
