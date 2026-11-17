"""
Diffusers-based generative adapters (GPU worker only; torch/diffusers imported
lazily). Covers the ReaVector workspace plan:

    text2image   : SDXL, Z-Image-Turbo
    image_edit   : FLUX-Kontext (image + prompt)
    image2video  : LTX-Video (image -> mp4)
    text2video   : Wan 2.1 1.3B (prompt -> mp4)
    texture      : SDXL image-to-image texture
    lora         : SDXL + a compatible LoRA

All are **unverified on a T4** here (no GPU in this environment). Each follows the
public diffusers API; confirm on Kaggle with bench/ai_bench before production.
Models that need >14.56 GB (FLUX fp16 ~16 GB) must be quantized/offloaded.
"""

from __future__ import annotations

import os

import torch  # module-level torch is fine on the worker; never imported on Render


def _prompt_from(input_path: str, params: dict) -> str:
    if params.get("prompt"):
        return str(params["prompt"])[:1024]
    if input_path and input_path.lower().endswith((".txt", ".md")):
        with open(input_path, "r", encoding="utf-8") as f:
            return f.read()[:1024] or "a product photo"
    return "a product photo, studio lighting"


def _maybe_lora(pipe, params: dict) -> None:
    """Load a compatible .safetensors LoRA into a diffusers pipeline."""
    lora = params.get("lora_path")
    if not lora:
        return
    if not str(lora).lower().endswith(".safetensors"):
        raise ValueError("only .safetensors LoRAs are allowed (no pickle)")
    pipe.load_lora_weights(lora)
    try:
        pipe.fuse_lora()
    except Exception:  # noqa: BLE001
        pass


class _DiffusersBase:
    name = "base"
    vram_gb = 10.0
    model_id = ""
    trust_remote_code = False

    def __init__(self, cache_dir: str = "./models"):
        self.cache_dir = cache_dir
        self.pipe = None

    def _device(self, params: dict) -> str:
        return params.get("device") or ("cuda" if torch.cuda.is_available() else "cpu")

    def _dtype(self):
        return torch.float16 if torch.cuda.is_available() else torch.float32

    def unload(self) -> None:
        self.pipe = None


# ---------------------------------------------------------------------------
# text-to-image (SDXL, Z-Image)
# ---------------------------------------------------------------------------
class Text2ImageAdapter(_DiffusersBase):
    name = "text2image"

    def load(self) -> None:
        from diffusers import AutoPipelineForText2Image
        self.pipe = AutoPipelineForText2Image.from_pretrained(
            self.model_id, torch_dtype=self._dtype(),
            trust_remote_code=self.trust_remote_code, use_safetensors=True)
        if torch.cuda.is_available():
            self.pipe.to("cuda")

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        if self.pipe is None:
            self.load()
        prompt = _prompt_from(input_path, params)
        image = self.pipe(
            prompt=prompt,
            num_inference_steps=int(params.get("steps", 30)),
            guidance_scale=float(params.get("guidance", 7.0)),
            width=int(params.get("width", 1024)), height=int(params.get("height", 1024)),
        ).images[0]
        path = os.path.join(out_dir, "output.png")
        image.save(path)
        return path


class SDXLAdapter(Text2ImageAdapter):
    name = "sdxl"
    vram_gb = 10.0
    model_id = os.environ.get("RV_SDXL_PATH", "stabilityai/stable-diffusion-xl-base-1.0")


class ZImageAdapter(Text2ImageAdapter):
    name = "z-image"
    vram_gb = 12.0
    model_id = os.environ.get("RV_ZIMAGE_PATH", "Tongyi-MAI/Z-Image-Turbo")
    trust_remote_code = True

    def load(self) -> None:
        import diffusers
        cls = getattr(diffusers, "ZImagePipeline", None)
        if cls is None:
            from diffusers import AutoPipelineForText2Image as cls
        self.pipe = cls.from_pretrained(self.model_id, torch_dtype=self._dtype())
        if torch.cuda.is_available():
            self.pipe.to("cuda")

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        if self.pipe is None:
            self.load()
        image = self.pipe(
            prompt=_prompt_from(input_path, params),
            num_inference_steps=int(params.get("steps", 8)),
            guidance_scale=float(params.get("guidance", 0.0)),
            height=int(params.get("height", 1024)), width=int(params.get("width", 1024)),
        ).images[0]
        path = os.path.join(out_dir, "output.png")
        image.save(path)
        return path


# ---------------------------------------------------------------------------
# image editing (FLUX-Kontext) — needs ~16 GB at fp16
# ---------------------------------------------------------------------------
class FluxEditAdapter(_DiffusersBase):
    name = "flux-edit"
    vram_gb = 16.0
    model_id = os.environ.get("RV_FLUX_PATH", "black-forest-labs/FLUX.1-Kontext-dev")

    def load(self) -> None:
        from diffusers import AutoPipelineForImage2Image
        self.pipe = AutoPipelineForImage2Image.from_pretrained(
            self.model_id, torch_dtype=self._dtype())
        if torch.cuda.is_available():
            self.pipe.enable_model_cpu_offload()

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        from PIL import Image
        os.makedirs(out_dir, exist_ok=True)
        if self.pipe is None:
            self.load()
        image = Image.open(input_path).convert("RGB")
        out = self.pipe(prompt=_prompt_from(None, params), image=image,
                        num_inference_steps=int(params.get("steps", 28)),
                        guidance_scale=float(params.get("guidance", 2.5)),
                        strength=float(params.get("strength", 0.6))).images[0]
        path = os.path.join(out_dir, "output.png")
        out.save(path)
        return path


# ---------------------------------------------------------------------------
# text-to-video (Wan 2.1 1.3B)
# ---------------------------------------------------------------------------
class WanText2VideoAdapter(_DiffusersBase):
    name = "wan2.1"
    vram_gb = 10.0
    model_id = os.environ.get("RV_WAN_PATH", "Wan-AI/Wan2.1-T2V-1.3B-Diffusers")

    def load(self) -> None:
        from diffusers import WanPipeline
        self.pipe = WanPipeline.from_pretrained(self.model_id, torch_dtype=self._dtype())
        if torch.cuda.is_available():
            self.pipe.to("cuda")

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        from diffusers.utils import export_to_video
        os.makedirs(out_dir, exist_ok=True)
        if self.pipe is None:
            self.load()
        _maybe_lora(self.pipe, params)
        frames = self.pipe(
            prompt=_prompt_from(input_path, params),
            num_inference_steps=int(params.get("steps", 30)),
            num_frames=int(params.get("frames", 49)),
            height=int(params.get("height", 480)), width=int(params.get("width", 832)),
        ).frames[0]
        path = os.path.join(out_dir, "output.mp4")
        export_to_video(frames, path, fps=int(params.get("fps", 16)))
        return path


# ---------------------------------------------------------------------------
# image-to-video (LTX-Video)
# ---------------------------------------------------------------------------
class LtxImage2VideoAdapter(_DiffusersBase):
    name = "ltx-video"
    vram_gb = 12.0
    model_id = os.environ.get("RV_LTX_PATH", "Lightricks/LTX-Video")

    def load(self) -> None:
        try:
            from diffusers import LTXImageToVideoPipeline as P
        except Exception:  # noqa: BLE001
            from diffusers import LTXPipeline as P  # older diffusers
        self.pipe = P.from_pretrained(self.model_id, torch_dtype=self._dtype())
        if torch.cuda.is_available():
            self.pipe.to("cuda")

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        from PIL import Image
        from diffusers.utils import export_to_video
        os.makedirs(out_dir, exist_ok=True)
        if self.pipe is None:
            self.load()
        image = Image.open(input_path).convert("RGB")
        _maybe_lora(self.pipe, params)
        out = self.pipe(image=image, prompt=_prompt_from(None, params),
                        num_inference_steps=int(params.get("steps", 30)),
                        num_frames=int(params.get("frames", 97)),
                        height=int(params.get("height", 512)),
                        width=int(params.get("width", 704))).frames[0]
        path = os.path.join(out_dir, "output.mp4")
        export_to_video(out, path, fps=int(params.get("fps", 24)))
        return path


# ---------------------------------------------------------------------------
# texture (SDXL image-to-image) — produces a texture image for a mesh
# ---------------------------------------------------------------------------
class TextureAdapter(_DiffusersBase):
    name = "texture"
    vram_gb = 12.0
    model_id = os.environ.get("RV_TEXTURE_PATH", "stabilityai/stable-diffusion-xl-base-1.0")

    def load(self) -> None:
        from diffusers import AutoPipelineForImage2Image
        self.pipe = AutoPipelineForImage2Image.from_pretrained(
            self.model_id, torch_dtype=self._dtype())
        if torch.cuda.is_available():
            self.pipe.to("cuda")

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        from PIL import Image
        os.makedirs(out_dir, exist_ok=True)
        if self.pipe is None:
            self.load()
        image = Image.open(input_path).convert("RGB").resize((1024, 1024))
        out = self.pipe(prompt=_prompt_from(None, params), image=image,
                        num_inference_steps=int(params.get("steps", 25)),
                        strength=float(params.get("strength", 0.5))).images[0]
        path = os.path.join(out_dir, "texture.png")
        out.save(path)
        return path


# ---------------------------------------------------------------------------
# LoRA (SDXL + compatible .safetensors)
# ---------------------------------------------------------------------------
class SdxlLoraAdapter(SDXLAdapter):
    name = "sdxl-lora"

    def run(self, input_path: str, params: dict, out_dir: str) -> str:
        if self.pipe is None:
            self.load()
        lora = params.get("lora_path")
        if lora:
            if not str(lora).lower().endswith(".safetensors"):
                raise ValueError("only .safetensors LoRAs are allowed (no pickle)")
            self.pipe.load_lora_weights(lora)
            self.pipe.fuse_lora()
        return super().run(input_path, params, out_dir)