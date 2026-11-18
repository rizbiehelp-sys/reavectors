# REAVECTOR — Repository & Live Application Audit (Phase 0)

Status: current as of this commit. This document is the required Phase 0 output and
supersedes earlier partial audits for the purpose of the master roadmap.

## 1. What the live app is

`reavectors.onrender.com` is a **standalone ReaVector application**. It is **not**
part of Madaripur Bazar and shares no database, users, products, auth or deployment.

Stack (verified in the repo, not assumed):

- **Backend:** pure standard-library Python `http.server` (`reavectors/server.py`),
  served by Render as a native Python service (`render.yaml`, `Dockerfile` present).
  No Flask/FastAPI/Django. No Node backend.
- **Frontend:** hand-written HTML/CSS/JS. No React/Vue/Astro build step. Three.js is
  vendored under `web/vendor/three/`.
- **Tests:** plain `python tests/test_*.py` scripts (no pytest dependency required).

## 2. Current sections (live)

| Route | Tool | State |
|---|---|---|
| `/` | 2D Vectorizer (Potrace/VTracer) | working |
| `/image.html` | AI Image (text→image, edit, texture) | working for SDXL-class |
| `/video.html` | AI Video (t2v, i2v) | adapter wired, not yet runnable |
| `/model3d.html` | AI 3D (image→3D → GLB viewer) | wired, runtime blocked |
| `/product3d.html` | Product 3D (parametric bottle + exact label) | working (CPU) |

Removed legacy pages (per earlier product direction): `/studio3d.html` (PNG
extrusion) and `/ai.html` (owner console) → now 404.

## 3. Backend inventory

- `reavectors/server.py` — routing, SSE (`/api/refine`), static serving with security
  headers, multipart parsing, API-key gate, CORS, rate limits.
- `reavectors/config.py` — all env knobs (upload limits, refine budget, AI/GPU,
  bridge, Kaggle, Cloudflare).
- `reavectors/security.py` — image validation, rate limiters, CSP, heavy gate.
- `reavectors/vectorize.py`, `refine.py`, `export.py`, `vtracer_engine.py` — the
  vectorizer core (Potrace + VTracer + SSE refine + SVG/PDF/EPS/AI export).
- `reavectors/db.py` — optional Supabase logging (stats/keepalive).
- `reavectors/ai/` — AI layer:
  - `registry.py` — 10-model registry (licence/VRAM/precision/limitations).
  - `scheduler.py` — dual-T4 placement, VRAM guard, one-job-per-GPU.
  - `manifest.py` — versioned run manifests.
  - `bridge.py` — durable job/artifact bridge (Supabase Storage; local fallback).
  - `kaggle_runner.py` — owner-only Kaggle kernel push (`kernels_push`), status.
  - `worker_models/` — triposr, sf3d, hunyuan3d, generative (SDXL/Z-Image/FLUX/
    LTX/Wan/texture/LoRA).
  - `lifecycle.py`, `providers.py`, `limits.py`, `store.py`, `models.py`,
    `catalog.py`, `service.py`, `worker.py`, `tripo.py` — legacy/auxiliary.
- `notebooks/` — `kaggle_main.ipynb` (batch worker), `kaggle_build_parts.ipynb`
  (weights in parts), plus bench notebooks.

## 4. Storage & persistence (Render constraints)

- Render free web service **sleeps** and has an **ephemeral filesystem**; nothing
  durable is stored there.
- **Job + artifact persistence is Supabase Storage** (`ai-bridge` bucket):
  `job_<id>.json`, `art_<id>.<ext>`, `meta_*`. Verified durable across a redeploy.
- Supabase DB is used only for lightweight stats/keepalive.
- The spec suggests Cloudflare R2/D1; **Supabase currently satisfies the same
  requirement** (survives restarts, out-of-band of Render). Migrating to R2/D1 is a
  later, optional swap behind the same bridge interface.

## 5. Job system

- States used today: `pending` (queued/waiting for GPU), `claimed`, `done`, `failed`.
- Jobs include: id, task, model, input_url, params, status, created/updated,
  claimed_at, artifact, bytes, manifest, error.
- Durable queue (Supabase), per-task daily caps, single-flight trigger, batch drain.
- Cancel = `fail`; retry = re-trigger. No separate `waiting_for_gpu`/`approval`
  states yet (spec asks for them — Phase 1 refinement).

## 6. Providers (truthful availability)

| Provider | State |
|---|---|
| Kaggle (manual kernel) | **configured** (2 accounts); push + batch worker proven |
| Colab | not implemented (spec: optional backup worker) |
| Hugging Face ZeroGPU | not implemented |
| Cloudflare Workers AI | **not implemented** (needed for live image API) |
| Lightning AI / Modal | documented only, disabled |

## 7. Measured results (real runs)

| Model | Result | Time |
|---|---|---|
| SDXL (text→image) | ✅ | 242.5 s |
| Texture (SDXL img2img) | ✅ | 238.1 s |
| Z-Image-Turbo | ⚠️ loads from mounted parts, **black output** (bf16 model, T4 has no bf16) | ~6 min |
| Wan 1.3B | ❌ 28.9 GB download > Kaggle disk | — |
| TripoSR | ❌ torchmcubes build (env fix in progress) | — |
| Product 3D (parametric) | ✅ CPU | ~30 s |

## 8. Known gaps vs the master spec

1. **Cloudflare Workers AI image adapter** — missing (Phase 1/2 requirement).
2. **Provider status UI** — no `/api/ai/providers` and no truthful availability panel.
3. **Job states** `waiting_for_gpu`, `awaiting_approval` — not modelled.
4. **Colab worker** — missing.
5. **Blender pipeline** (`blender/scripts/*`) — missing.
6. **R2/D1** — using Supabase instead (acceptable; swap later).
7. **Reference-video analysis / motion graphics** — missing.
8. **3D AI runtime** — TripoSR env fragile; TRELLIS.2 needs ≥24 GB (not T4).

## 9. Preserve / do not break

- Vectorizer tracing + SVG/PDF/EPS/AI exports and the SSE refine budget.
- Product 3D parametric reconstruction + label rectification.
- Bridge durability and owner-only worker token.
- CSP (`script-src 'self'`): **no inline scripts**; all page JS must be external files.

## 10. Next (Phase 1 remaining work)

1. `/api/ai/providers` + a provider status strip in the UI (truthful).
2. Cloudflare Workers AI image adapter (disabled unless configured).
3. Job lifecycle: add `waiting_for_gpu` + `awaiting_approval`, cancel/retry semantics.
4. Colab worker notebook sharing the same protocol.