# Benchmarks — measured on Kaggle T4 ×2

Reproducible runs via `notebooks/kaggle_bench.ipynb`, `notebooks/kaggle_bench3d.ipynb`
and `scripts/ai_bench.py`. Reports are written to `bench/results/` (git-ignored).

## Verified

| Model | GPU | Result | Time | Peak VRAM | Output |
|---|---|---|---|---|---|
| **SDXL** (`sdxl-base-1.0`) | 0 (T4) | ✅ **works** | **150.99 s** | **9.73 GB** | 1024² PNG (1.1 MB) |

Environment: torch 2.11.0+cu130 · CUDA 13.0 · Tesla T4 (14.56 GB) · Python 3.13.

## Blocked on Kaggle's default environment

| Model | Blocker |
|---|---|
| **TripoSR** | needs `torchmcubes`; it has no wheel and **does not build** against Kaggle's torch 2.11/cu130 (and torch 2.4 is no longer on the cu121 index). |
| **SF3D** | pins `numpy==1.26.4` + builds local C++ packages (`texture_baker`, `uv_unwrapper`, `pynanoinstantmeshes`) — fragile against the preinstalled stack. |

The adapters, registry and scheduler are complete; `scripts/ai_bench.py --models triposr`
will report a real number **once a compatible runtime exists**.

## Recommended fix for 3D (pick one)

1. **Pinned PyTorch env** — a Kaggle kernel that installs a torch version
   `torchmcubes` supports (torch 2.1–2.4 + matching cu121) in a clean venv, then
   `pip install --no-build-isolation torchmcubes`. Verify `import torchmcubes`.
2. **SF3D in its own env** — fresh venv, `pip install -r stable-fast-3d/requirements.txt`
   from inside the repo dir, then bench; keep it isolated from the image stack.
3. **Custom Docker image** (TripoSR/SF3D prebuilt) — most reliable, no per-run builds.

No result is fabricated: image is measured; 3D awaits a working runtime.

## Web/bridge end-to-end (owner Kaggle runs)

| # | Model | Task | Result | Wall time | Now |
|---|---|---|---|---|---|
| 1 | SDXL | text2image | **works** | **242.5 s** | verified (output in Downloads) |
| 2 | Texture (SDXL img2img) | texture | **works** | **238.1 s** | verified (output in Downloads) |
| 3 | Z-Image-Turbo | text2image | **fails** | 444.5 s wasted | dies at 92% of a **12 GB** download -> Kaggle disk too small |
| 4 | FLUX-Kontext | image_edit | not run | - | 24 GB download -> will not fit Kaggle disk |
| 4b | Wan 2.1 1.3B | text2video | **fails** | 368.3 s wasted | dies at ~98% of an 8 GB download (disk/network limit) |
| 5 | LTX-Video | image2video | not run | - | 10 GB, may fit but tight |
| 6 | Wan 2.1 1.3B | text2video | not run | - | 8 GB |
| 7 | TripoSR | image2_3d | blocked | - | torchmcubes will not build on Kaggle torch 2.11 |
| 8 | SF3D | image2_3d | blocked | - | numpy pin + local C++ builds |
| 9 | Hunyuan3D | image2_3d | blocked | - | 24 GB VRAM > T4 |

Runs used: SDXL 2 kernels (1 dep-fix + 1 success); Texture 1; Z-Image 2 (1 bad-input + 1 disk-fail).

Constraint: Kaggle's container disk (~20 GB) cannot hold the 12-24 GB image models.
Fix: attach weights as a **Kaggle Dataset** (mounted, not downloaded per run) or use quantized variants.


## Hard limit found: repo sizes vs Kaggle disk

| Repo | Total size | Fits Kaggle (~8-20 GB)? |
|---|---|---|
| stabilityai/stable-diffusion-xl-base-1.0 | ~7 GB | yes (works) |
| Tongyi-MAI/Z-Image-Turbo | 32.9 GB | **no** |
| Wan-AI/Wan2.1-T2V-1.3B-Diffusers | 28.9 GB | **no** (T5 encoder ~23 GB) |
| Lightricks/LTX-Video | large (13B variants) | no |
| black-forest-labs/FLUX.1-Kontext-dev | ~24 GB | no |

Z-Image / Wan / LTX / FLUX cannot run on Kaggle free tier: the download (or the
dataset build) dies with "No space left on device". Only SDXL-class models fit.
