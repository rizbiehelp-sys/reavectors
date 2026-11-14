# Model benchmarking — Kaggle (dev) → AWS (production)

`kaggle_benchmark.py` produces a **reproducible report** for any model adapter:
model name, weights/version, license, inference time, peak VRAM, output
resolution, mesh stats and quality notes. It runs unchanged on **Kaggle** (dual
T4, personal dev) and on the **AWS g4dn.xlarge** worker, because both use the same
adapters in `reavectors/ai/worker_models/`.

## Kaggle terms (must respect)

Kaggle permits **personal, non-commercial** use and prohibits using the service on
behalf of third parties. **Do not** connect Kaggle notebooks, tunnels, polling
workers or endpoints to public ReaVector customer requests without Kaggle's written
authorisation. AWS is the authorised public production environment.

## Confirmed Kaggle hardware

Tesla T4 ×2 · ~14.56 GB usable VRAM each · PyTorch 2.11.0+cu128 · CUDA 12.8 · CC 7.5.

Test independent workloads on the two GPUs and monitor each one's VRAM separately:

```bash
# GPU 0
CUDA_VISIBLE_DEVICES=0 python bench/kaggle_benchmark.py --image data/product.png --models triposr
# GPU 1 (in a second cell / process)
CUDA_VISIBLE_DEVICES=1 python bench/kaggle_benchmark.py --image data/product.png --models sf3d
```

## Usage

```bash
python bench/kaggle_benchmark.py --list                 # roadmap + which adapters are live
python bench/kaggle_benchmark.py --image examples/chair.png --models triposr,sf3d
python bench/kaggle_benchmark.py --out ./bench/results  # writes JSON + a markdown table
```

## Roadmap

| model | kind | weights | license | status |
|---|---|---|---|---|
| triposr | image→3d | `stabilityai/TripoSR` | MIT | **adapter live** |
| sf3d | image→3d | `stabilityai/stable-fast-3d` | Stability AI Community License | **adapter live** |
| sdxl | image | `stabilityai/stable-diffusion-xl-base-1.0` | CreativeML Open RAIL++-M | planned |
| z-image | image | `Tongyi-MAI/Z-Image` | Apache-2.0 (verify) | planned |
| ltx-video | video | `Lightricks/LTX-Video` | LTX-Video license (verify) | planned |
| wan2.1 | video | `Wan-AI/Wan2.1-T2V-14B` | Apache-2.0 | planned |

Only **adapters marked live** are selectable in production. Everything else is
recorded so reports stay comparable as adapters land.

## Reports

Each run writes `bench/results/benchmark-<run_id>.json` and a matching `.md`. Commit
only the **reports** (never weights). A report is the evidence used to pick
production defaults — see `docs/MODEL_LICENSES.md`.
