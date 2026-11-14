"""
Model + LoRA catalogue.

Built-in entries are metadata only and carry an explicit ``enabled`` flag. A model
is NOT enabled for public production until its exact code and weights licences
are verified (see docs/MODEL_LICENSES.md). Nothing here loads code or weights.
"""

from __future__ import annotations

from .models import JobType

# Built-in image/video/3D model adapters. `enabled` stays False until the licence
# checklist in docs/MODEL_LICENSES.md is completed for the exact version.
BUILTIN_MODELS = [
    {
        "id": "sdxl-base-1.0",
        "task": JobType.TEXT_TO_IMAGE.value,
        "name": "SDXL Base 1.0 (fp16)",
        "adapter": "diffusers",
        "enabled": False,
        "license_status": "VERIFY (CreativeML OpenRAIL++-M) — hosted-service terms",
        "notes": "T4 16GB; single active job. Enable only after licence review.",
    },
    {
        "id": "triposr",
        "task": JobType.IMAGE_TO_3D.value,
        "name": "TripoSR",
        "adapter": "triposr",
        "enabled": False,
        "license_status": "VERIFY code (MIT claim) + exact checkpoint terms",
        "notes": "Single-object images; transparent PNG accepted.",
    },
    {
        "id": "ltx-video-2b",
        "task": JobType.IMAGE_TO_VIDEO.value,
        "name": "LTX-Video 2B (distilled)",
        "adapter": "diffusers",
        "enabled": False,
        "license_status": "VERIFY version + distilled weights licence + T4 benchmark",
        "notes": "Async job; own timeout and daily cap.",
    },
    {
        "id": "wan2.1-1.3b-t2v",
        "task": JobType.TEXT_TO_VIDEO.value,
        "name": "Wan 2.1 1.3B T2V",
        "adapter": "diffusers",
        "enabled": False,
        "license_status": "VERIFY version + weights licence + VRAM benchmark",
        "notes": "Low-res short clips first; benchmark T4 memory.",
    },
]

# Built-in LoRA library (metadata). Only enabled entries whose licence permits
# hosted use may be exposed; user-uploaded LoRAs are stored separately.
BUILTIN_LORAS = [
    {
        "id": "builtin-logo-flat",
        "name": "Flat Logo Style",
        "base": "sdxl",
        "trigger": "flat logo, vector style",
        "weight": 0.7,
        "license": "VERIFY before enabling",
        "source_url": "",
        "active": False,
        "preview": "/vendor/lora/placeholder.svg",
    },
]


def models_for(job_type: str = None) -> list:
    if job_type:
        return [m for m in BUILTIN_MODELS if m["task"] == job_type]
    return list(BUILTIN_MODELS)


def enabled_models() -> list:
    return [m for m in BUILTIN_MODELS if m.get("enabled")]


def builtin_loras() -> list:
    return list(BUILTIN_LORAS)
