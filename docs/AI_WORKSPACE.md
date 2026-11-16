# ReaVector AI workspace — Kaggle T4 ×2 (main, only GPU)

Colab is **dropped**. All GPU work is Kaggle T4 ×2, **owner/personal** only. AWS stays
an always-on VPS for WAHA (untouched, no GPU). No paid GPU APIs.

## Verdict on "Kaggle main"
Good for **your** development jobs. **Not** a public inference endpoint: Kaggle's
terms forbid third-party/public use and sessions are not callable live. So Render
never calls Kaggle — they exchange **jobs + artifacts** through a bridge.

## Layout

```
browser ──► Render (Python API: parametric 3D, bridge, serves artifacts)
                │  queue job            ▲ upload GLB/MP4
                ▼                       │
          Kaggle notebook (T4 1) ───────┘
          (owner pulls, runs, uploads)
```

## Model registry (`reavectors/ai/registry.py`)

One record per model: repo, revision, licence, commercial note, VRAM, download,
precision, ~seconds, quality, limitations, adapter, GPU, status.

| id | task | GPU | VRAM | licence | status |
|---|---|---|---|---|---|
| sdxl-base-1.0 | text2image | 0 | 10 | OpenRAIL++-M | planned |
| z-image-turbo | text2image | 0 | 12 | Apache-2.0 (VERIFY) | planned |
| flux-kontext-dev | image_edit | 0 | 16 → quantize | FLUX dev (non-commercial) | planned |
| lora-sdxl | lora | 0 | 10 | per-LoRA | planned |
| ltx-video | image2video | 1 | 12 | LTX (VERIFY) | planned |
| wan2.1-1.3b | text2video | 1 | 10 | Apache-2.0 | planned |
| triposr | image2_3d | 1 | 6 | MIT | **live** |
| sf3d | image2_3d | 1 | 6.5 | Stability Community | **live** |
| hunyuan3d-2.1 | image2_3d | — | 24 | Tencent Community | **24 GB — not a T4** |
| texture-sdxl-inpaint | texture | 0 | 12 | OpenRAIL++-M | planned |

`registry.validate()` enforces the required fields (CI/test).

## Scheduler (`reavectors/ai/scheduler.py`)

- task → GPU map (0: image/lora/texture, 1: video/3D), configurable.
- **one job per GPU** (a lock per GPU) → no VRAM exhaustion.
- **VRAM guard**: Hunyuan3D (24 GB) is refused on a 14.56 GB T4 up-front.
- model caching per GPU; `unload()` frees VRAM.
- the two T4s are **independent** pools, never 29 GB.
- For real parallelism: `scripts/gpu_job.py --gpu 0|1` in separate processes
  (`CUDA_VISIBLE_DEVICES` is process-wide), or the notebook.

## Storage + manifests (`reavectors/ai/manifest.py`)

- `JobWorkspace` writes each run to `<root>/<run_id>__<model>/`.
- `manifest.json` records model spec, inputs, params, timings, GPU, output hashes.
- Kaggle's FS does not survive a restart — **upload/persist before the session ends**
  (`persist()`, or the bridge upload).

## Bridge (`reavectors/ai/bridge.py` + `/api/ai/bridge/*`)

Owner-only job/artifact exchange (needs `X-Bridge-Key` = `AI_BRIDGE_KEY`):

1. `POST /api/ai/bridge/jobs` — queue `{task, model, input_url, params}`.
2. `GET  /api/ai/bridge/jobs?status=pending` — notebook pulls.
3. `POST /api/ai/bridge/jobs/<id>/claim` — take it.
4. `POST /api/ai/bridge/jobs/<id>/result` — upload `file` + `filename` (+ manifest).
5. `GET  /api/ai/bridge/artifacts/<id>.glb` — public; the studio loads it.

If `AI_BRIDGE_KEY` is unset the whole bridge is **403** (safe default). Artifacts are
the only public part, so the website can display results.

## Benchmarking (`scripts/ai_bench.py`)

Per GPU (`--gpu 0|1`), writes `bench/results/bench-gpu<N>-<utc>.json|.md` with
seconds, **peak VRAM**, bytes and failures. `--list` / `--dry-run` need no GPU.

## On-demand trigger (Kaggle API)

Owner-only `POST /api/ai/bridge/trigger` (needs `X-Bridge-Key`) turns a queued job
into a **running Kaggle GPU kernel**:

1. body `{task, model, input_url, params}` (or `{job_id}`) — queues/fetches the job.
2. `reavectors/ai/kaggle_runner.py` builds a **private** kernel from
   `notebooks/kaggle_main.ipynb` (bridge key injected, `enable_gpu: true`) and calls
   Kaggle's `kernels push`.
3. the kernel runs on a T4, pulls the job, runs it, uploads the GLB to the bridge.
4. `GET /api/ai/bridge/kernel?ref=owner/slug` returns the kernel status.

Requires `KAGGLE_USERNAME` + `KAGGLE_KEY` (from `kaggle.json`) in Render env — never
committed. Not instant: Kaggle queues the kernel (minutes) and enforces the weekly
GPU quota. Still personal/owner use only.

## Safety

- No AWS GPU, no paid GPU API, no automatic paid fallback.
- WAHA t3.micro untouched.
- Kaggle credentials live only in the notebook/Render env, never in frontend or git.
- Kaggle is owner/personal only.

## What the owner must provide

- **`AI_BRIDGE_KEY`** in Render env (and the notebook) — I can generate and set it.
- Nothing else: Render + the bridge + notebooks are complete.
- Optional: a Kaggle API token only if you want me to push/trigger notebooks
  automatically; otherwise you paste the cells and run manually.