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