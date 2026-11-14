# Compute layout — Kaggle GPU + Render/Cloudflare + always-on VPS

## Roles

| Layer | Runs on | What it does |
|---|---|---|
| Frontend / CDN / cache | **Cloudflare** | static `web/`, caching, TLS |
| API (Python `http.server`) | **Render** | Product 3D parametric pass, jobs, API |
| **GPU inference** | **Kaggle** (owner, personal) | TripoSR / SF3D / Hunyuan3D → GLB |
| Always-on VPS | **AWS t3.micro** (existing) | relay / heartbeat / small always-active task |

There is **no AWS GPU** and **no hosted paid 3D API** anymore. GPU work is done on
Kaggle by you (the owner) and the resulting `.glb` is opened in the studio.

## Why not AWS GPU
The g4dn/g5 instances are **not free tier** and only bill by the hour. Kaggle gives
you two free T4s for personal use, so we use Kaggle for all GPU inference.

## Kaggle GPU (all GPU usage)

See **`kaggle/README.md`** for copy-paste cells. Short version:

1. Notebook → Accelerator **GPU T4 ×2**.
2. `git clone` the repo, `pip install -r` the model repo (TripoSR / SF3D).
3. `python scripts/ai3d_run.py --image <photo> --model triposr --out out.glb`.
4. Studio → **Open a .glb (from Kaggle)** → the model loads in the viewer.

`bench/kaggle_benchmark.py` writes a report (time, **peak VRAM**, licence, quality)
so you can pick the default per job.

> Kaggle terms: personal, non-commercial. Do **not** connect Kaggle sessions or
> tunnels to public ReaVector customer requests without Kaggle's written
> authorisation. Generate manually and open the GLB.

## Models

| Model | VRAM | Fits T4? | Licence |
|---|---|---|---|
| **TripoSR** | ~6 GB | ✅ | MIT |
| **SF3D** | ~6.5 GB | ✅ | Stability AI Community |
| **Hunyuan3D-2.1** | ~24 GB | ❌ (needs g5/g6) | Tencent Hunyuan Community |

## Always-on VPS (AWS)

The existing **t3.micro** is enough for a lightweight always-on relay/heartbeat.
If you want to self-host the Python API or run a small queue on the VPS:

- **t3.micro** (1 GB) — fine for a relay only; too small for the app + tools.
- **m7i-flex.large** (2 vCPU / 8 GB) — comfortable if you move the API off Render
  or add a worker/queue there. Not free tier (~$0.08–0.10/hr when running).
- Free-tier options are only `t3.micro`/`t2.micro`; there is no free larger box.

Recommendation: keep **t3.micro** as the always-on relay; keep the API on **Render**
and static on **Cloudflare**. Only upgrade the VPS if you decide to self-host the API.

## Backend location

- **Render** — the Python service (`reavectors/server.py`): Product 3D parametric
  reconstruction, job API, `/api/health`, `/api/stats`.
- **Cloudflare** — serve `web/` (index, studio3d, product3d) and cache static assets.
  The current server also serves these; moving them to Cloudflare Pages is optional.