"""
Unified AI model registry (Kaggle dual-T4 development).

One declarative record per model, covering every ReaVector AI task. The scheduler
and benchmark read from here, so features are not disconnected. Nothing here
imports torch; it is pure data + helpers and safe to import on the API/web tier.

Every record documents: repo, revision, licence, commercial-use note, VRAM,
download size, precision, approximate inference time, quality and limitations.
Fields marked "VERIFY" must be confirmed against the model card before enabling.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass

TASKS = ("text2image", "image_edit", "lora", "image2video", "text2video",
         "image2_3d", "texture")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    task: str
    repo: str
    revision: str
    license: str
    commercial: str
    vram_gb: float
    download_gb: float
    precision: str
    approx_seconds: float
    quality: str
    limitations: str
    adapter: str = ""       # key in worker_models ("" = no adapter yet)
    gpu: str = "any"        # preferred "0" / "1" / "any"
    status: str = "planned"  # "adapter_live" | "planned"

    def to_dict(self) -> dict:
        return asdict(self)


REGISTRY: list[ModelSpec] = [
    # ---- text-to-image (GPU 0) -------------------------------------------
    ModelSpec("sdxl-base-1.0", "text2image", "stabilityai/stable-diffusion-xl-base-1.0",
              "main (VERIFY)", "CreativeML OpenRAIL++-M", "conditional (use restrictions)",
              10.0, 7.0, "fp16", 30.0, "high, mature + LoRA ecosystem",
              "1024px-native; needs LoRA for styles; safety filter per licence",
              adapter="sdxl", gpu="0", status="adapter_live"),
    ModelSpec("z-image-turbo", "text2image", "Tongyi-MAI/Z-Image-Turbo",
              "main (VERIFY)", "Apache-2.0 (VERIFY)", "yes (VERIFY)",
              12.0, 12.0, "fp16/bf16", 12.0, "fast, good prompt adherence",
              "verify ops/attention on T4 (cc 7.5); bf16 may fall back to fp16",
              adapter="z-image", gpu="0", status="adapter_live"),
    # ---- image editing (GPU 0) -------------------------------------------
    ModelSpec("flux-kontext-dev", "image_edit", "black-forest-labs/FLUX.1-Kontext-dev",
              "main (VERIFY)", "FLUX.1 [dev] Non-Commercial License", "no (non-commercial)",
              14.0, 24.0, "fp16 + cpu offload", 90.0, "strong instruction editing",
              "24 GB download; >14.56 GB at fp16 -> cpu offload; non-commercial",
              adapter="flux-edit", gpu="0", status="adapter_live"),
    # ---- LoRA (GPU 0) ----------------------------------------------------
    ModelSpec("lora-sdxl", "lora", "user-supplied / built-in SDXL LoRAs",
              "per-LoRA", "per-LoRA (must permit hosted use)", "per-LoRA",
              10.0, 0.2, "fp16", 2.0, "style/character injection",
              "load only .safetensors; never pickle; enforce SDXL family match",
              adapter="sdxl-lora", gpu="0", status="adapter_live"),
    # ---- image-to-video (GPU 1) -----------------------------------------
    ModelSpec("ltx-video", "image2video", "Lightricks/LTX-Video",
              "main (VERIFY)", "LTX-Video license (VERIFY)", "conditional (VERIFY)",
              12.0, 10.0, "fp16", 90.0, "fast short clips",
              "short durations; distilled weights may have separate terms",
              adapter="ltx-video", gpu="1", status="adapter_live"),
    # ---- text-to-video (GPU 1) ------------------------------------------
    ModelSpec("wan2.1-1.3b", "text2video", "Wan-AI/Wan2.1-T2V-1.3B",
              "main (VERIFY)", "Apache-2.0", "yes",
              10.0, 8.0, "fp16", 120.0, "1.3B small model, good motion",
              "low resolution vs 14B; longer clips need more VRAM",
              adapter="wan2.1", gpu="1", status="adapter_live"),
    # ---- image-to-3D (GPU 1) --------------------------------------------
    ModelSpec("triposr", "image2_3d", "stabilityai/TripoSR",
              "main", "MIT", "yes",
              6.0, 1.6, "fp16", 1.0, "good single-image mesh (vertex colour)",
              "backside inferred; branding is generated, not preserved",
              adapter="triposr", gpu="1", status="adapter_live"),
    ModelSpec("sf3d", "image2_3d", "stabilityai/stable-fast-3d",
              "main", "Stability AI Community License (<$1M revenue)", "conditional",
              6.5, 3.0, "fp16", 2.0, "higher detail + baked texture",
              "single image; verify licence threshold before >$1M",
              adapter="sf3d", gpu="1", status="adapter_live"),
    ModelSpec("hunyuan3d-2.1", "image2_3d", "tencent/Hunyuan3D-2.1",
              "main (VERIFY)", "Tencent Hunyuan 3D Community License", "conditional",
              24.0, 12.0, "fp16", 60.0, "best quality (Tripo-class)",
              "~24 GB VRAM -> does NOT fit a T4 (14.56 GB); needs a bigger GPU",
              adapter="hunyuan3d", gpu="any", status="adapter_live"),
    # ---- texture generation (GPU 0) -------------------------------------
    ModelSpec("texture-sdxl-inpaint", "texture", "stabilityai/stable-diffusion-xl-base-1.0 (inpaint)",
              "main (VERIFY)", "CreativeML OpenRAIL++-M", "conditional (use restrictions)",
              12.0, 7.0, "fp16", 20.0, "projection texturing for meshes",
              "UV projection quality varies; verify texture seam handling",
              adapter="texture", gpu="0", status="adapter_live"),
]

_BY_ID = {m.id: m for m in REGISTRY}


def get(model_id: str) -> ModelSpec:
    if model_id not in _BY_ID:
        raise KeyError(f"unknown model id: {model_id}")
    return _BY_ID[model_id]


def by_task(task: str) -> list[ModelSpec]:
    return [m for m in REGISTRY if m.task == task]


def by_gpu(gpu: str) -> list[ModelSpec]:
    return [m for m in REGISTRY if m.gpu in (gpu, "any")]


def adapters() -> list[ModelSpec]:
    return [m for m in REGISTRY if m.adapter and m.status == "adapter_live"]


def manifest() -> dict:
    """Reproducible model manifest (commit this / store with outputs)."""
    return {
        "schema": "reavectors.model-manifest/1",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tasks": list(TASKS),
        "models": [m.to_dict() for m in REGISTRY],
    }


def validate() -> list[str]:
    """Return a list of problems (empty == valid). Used by tests/CI."""
    problems = []
    seen = set()
    for m in REGISTRY:
        if m.id in seen:
            problems.append(f"duplicate id: {m.id}")
        seen.add(m.id)
        if m.task not in TASKS:
            problems.append(f"{m.id}: unknown task {m.task}")
        for field in ("repo", "revision", "license", "commercial", "precision",
                      "quality", "limitations"):
            if not getattr(m, field):
                problems.append(f"{m.id}: empty {field}")
        if m.vram_gb <= 0 or m.download_gb < 0 or m.approx_seconds <= 0:
            problems.append(f"{m.id}: bad numeric field")
        if m.gpu not in ("0", "1", "any"):
            problems.append(f"{m.id}: bad gpu {m.gpu}")
        if m.status not in ("adapter_live", "planned"):
            problems.append(f"{m.id}: bad status {m.status}")
    return problems