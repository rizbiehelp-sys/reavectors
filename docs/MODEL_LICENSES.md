# MODEL LICENSES & PROVIDER MATRIX

> **Rule:** nothing is enabled in public production until the **exact** version,
> weights and code licence are verified against the official source. This file is
> a **tracker**, not a legal opinion. "VERIFY" means: open the linked source and
> confirm the licence for the exact checkpoint you intend to host.

## Chosen free image→3D: TripoSR (MIT)

Confirmed from the official repo (2026-11): **TripoSR** (VAST-AI-Research /
Stability AI) is released under the **MIT licence — code, pretrained weights and
demo**. Single image → mesh, ~6 GB VRAM, <0.5 s on A100 (slower on a T4 but
usable), optional `--bake-texture`. It is literally by the Tripo team, so it is
the closest free "Tripo-quality" option and fits the T4. This is the model the
GPU worker targets (`reavectors/ai/worker_models/triposr.py`).

| Free option | Quality | VRAM | T4 OK? | Licence | Verdict |
|---|---|---|---|---|---|
| **TripoSR** | good (vertex colour; `--bake-texture`) | ~6 GB | ✅ | **MIT** | **chosen** |
| Hunyuan3D-2.1 | higher, PBR | ~24 GB+ | partial (lite) | Tencent Hunyuan (verify) | later |
| TRELLIS (Microsoft) | SOTA | needs Ampere+ (flash-attn) | ❌ (Turing) | MIT-ish (verify) | not on T4 |
| LGM / Unique3D / SF3D | varies | varies | varies | verify | candidates |

## Candidate models

| Feature | Model (candidate) | Code licence | Weights licence | Hosted-service allowed? | Status |
|---|---|---|---|---|---|
| Text→Image | **SDXL Base 1.0** (fp16) | stability-ai/generative-models (VERIFY version) | **CreativeML OpenRAIL++-M** (VERIFY exact) | OpenRAIL permits hosting **with use restrictions** — review | VERIFY |
| Image→3D | **TripoSR** | **MIT** (confirmed) | **MIT** (code + weights + demo) | Permitted (MIT) | **adapter live** |
| Image→Video | **LTX-Video 2B distilled** | VERIFY repo | VERIFY (distilled weights may differ) | VERIFY | VERIFY |
| Text→Video | **Wan 2.1 1.3B T2V** | VERIFY repo | VERIFY | VERIFY | VERIFY |
| Image→3D (opt-in) | **SF3D** (`stabilityai/stable-fast-3d`) | VERIFY repo | **Stability AI Community License** (free personal + commercial < USD 1M revenue; enterprise above) | Permitted under Community License — review before >$1M | **adapter live** |
| Image→3D (quality) | **Hunyuan3D-2.1** (`tencent/Hunyuan3D-2.1`) | VERIFY repo | **Tencent Hunyuan 3D Community License** (< 100M MAU; territory limits — verify EU/UK/KR) | Permitted under Community License; review territory | **adapter live** (~24 GB → g5/g6) |

Verification checklist per model (fill in before enabling):

1. Exact repository URL + commit/tag.
2. Code licence file (SPDX id).
3. Weights licence / model card terms (may differ from code).
4. Explicit statement about **hosted inference for third parties**.
5. Commercial-use clause and any use-restriction policy (OpenRAIL has one).
6. Attribution requirements.
7. Any gating (HF "gated" repos require accepting terms per account).

## LoRAs

| Source | Constraint |
|---|---|
| Built-in library | Each entry records base model, licence, source URL, trigger words. Only entries whose licence permits hosted use are enabled. |
| User uploads | `.safetensors` only. **Never** loaded as code (no pickle/`.bin`/`.pt` with code). Metadata inspected; base-family compatibility enforced. |

## Inference providers (fallbacks — optional, all default OFF)

| Provider | Free tier | Rate limit | Custom LoRA | Licence of served models | Status |
|---|---|---|---|---|---|
| Cloudflare Workers AI | VERIFY current terms | VERIFY | VERIFY | per-model | DISABLED |
| Hugging Face Inference Providers | VERIFY | VERIFY | VERIFY | per-model | DISABLED |
| OVHcloud AI Endpoints | VERIFY | VERIFY | VERIFY | per-model | DISABLED |

- Global flags: `AI_USE_API_FALLBACK=0`, `AI_ALLOW_PAID_FALLBACK=0` (default).
- A fallback must **never** silently drop a requested LoRA. If the provider can't
  honour it, the job queues or fails with a clear reason.
- No provider is presented as operational until verified (`availability_status`).

## Compliance notes for this deployment

- GPT/other **text** LLMs are out of scope here; this is image/video/3D only.
- OpenRAIL-family models (SDXL) carry **use restrictions** that bind downstream
  hosting — surface them in the app's terms before enabling.
- Keep a per-model `enabled` flag in the catalogue; production enables are gated
  on the checklist above being completed and recorded here.
