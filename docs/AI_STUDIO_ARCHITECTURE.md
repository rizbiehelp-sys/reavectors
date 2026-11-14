# AI STUDIO ARCHITECTURE

How the AI Studio maps onto the **actual** ReaVector repo (stdlib Python server +
vanilla JS). No framework migration. GPU compute scales to zero.

## 1. Logical architecture

```
  Browser (vanilla JS, Three.js vendored locally)
      │  same-origin fetch
      ▼
  ReaVector app (existing stdlib http.server)      ← runs on Render or the t3.micro
      ├─ existing: /api/vectorize /api/export /api/refine /api/stats /api/health
      └─ NEW:      /api/ai/*  (job API)
      │
      ├─ SQLite (WAL)  → job registry, users, quota counters, GPU usage, LoRA catalogue
      ├─ Queue adapter  → in-process SQLite queue (default)  |  AWS SQS (opt-in)
      ├─ GPU lifecycle manager (race-safe) → MockGPUProvider (default) | EC2Provider (disabled)
      └─ Storage adapter → local private dir (dev) | S3 presigned (opt-in)
      │
      ▼
  On-demand GPU EC2 worker (g4dn.xlarge / T4) — SQS polling, heartbeat, IAM instance profile
      │  reads inputs from private S3, writes outputs to private S3
      ▼
  Cloudflare Worker (edge validation + rate limit) → forwards to the app
```

The **controller stays lightweight** (no Redis/Postgres/ComfyUI on the t3.micro).
The GPU worker is the only component that loads models.

> The Cloudflare Worker is optional in this implementation pass; the app already
> enforces validation + rate limiting, so the edge layer is an additional control,
> not a dependency.

## 2. Module layout added to the repo

```
reavectors/ai/
├── __init__.py
├── store.py        # SQLite (WAL): jobs, users, quotas, gpu_usage, loras, settings
├── models.py       # dataclasses + enums (JobType, JobState) + validation rules
├── lifecycle.py    # GPU state machine + provider interface (mock / ec2)
├── providers.py    # MockGPUProvider (default), EC2Provider (disabled, boto3)
├── queue.py        # Queue interface (SQLite now, SQS later)
├── limits.py       # per-user / global quotas, cost guard
├── catalog.py      # built-in models + LoRA library
├── api.py          # /api/ai/* handlers (called from server.Handler)
└── storage.py      # local private storage (dev) + S3 adapter skeleton

web/studio3d.html   # browser-only PNG/SVG -> 3D editor
web/studio3d.js
web/vendor/three/    # vendored three.module.js + addons (keeps CSP first-party)
```

`server.py` gains only thin route dispatch into `ai.api` — the existing routes are untouched.

## 3. API (adapted to existing conventions; JSON, `{"error":…}` on failure)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ai/jobs` | submit a job → **202** `{job_id, status, queue_position}` |
| GET | `/api/ai/jobs/{id}` | job status/result |
| POST | `/api/ai/jobs/{id}/cancel` | cancel if not terminal |
| GET | `/api/ai/jobs/history` | caller's recent jobs |
| GET | `/api/ai/capacity` | queue depth, GPU state, budget remaining |
| GET | `/api/ai/models` | enabled model adapters |
| GET | `/api/ai/loras` | built-in + user LoRAs |
| POST | `/api/ai/loras/upload` | register a user LoRA (`.safetensors`) |
| DELETE | `/api/ai/loras/{id}` | delete a user LoRA |

Job types: `text_to_image`, `image_to_video`, `text_to_video`, `image_to_3d`.
**Browser 3D extrusion is NOT a job** (no GPU).

States: `created → queued → waking_gpu → booting → loading_model → running →
saving_result → succeeded | failed | cancelled | timed_out`.

Idempotency: `POST /api/ai/jobs` accepts `Idempotency-Key`; duplicates return the
existing job. Ownership: a job is only visible to its owner (or an admin key).

## 4. GPU lifecycle (most important subsystem)

```
STOPPED → STARTING → BOOTING → INITIALIZING → READY → BUSY → IDLE_GRACE → STOPPING → STOPPED
```

- **Start is lock-guarded:** N simultaneous submissions produce **one** start call.
  Extra requests are enqueued with the same `job_id`.
- **Readiness is not "EC2 running".** The worker must publish a *model-ready*
  heartbeat; the controller waits for that before dispatching.
- **Idle shutdown:** after `IDLE_GRACE_SECONDS` with no queued/active work, a
  shutdown lock is taken and conditions are **re-checked** before `StopInstances`.
- **Crash/restart recovery:** on boot, reconcile DB state against
  `DescribeInstances`, expire leases, requeue orphans.
- **Single worker first:** `MAX_GPU_ACTIVE_JOBS=1`.

Providers implement one interface:

```python
class GPUProvider(Protocol):
    def state(self) -> str            # stopped|starting|running|...
    def start(self) -> None           # idempotent
    def stop(self) -> None            # idempotent
    def worker_ready(self) -> bool    # from heartbeat store
```

- `MockGPUProvider` — default; simulates timing; used by all tests. **No AWS.**
- `EC2Provider` — boto3; **refuses to act** unless `AI_GPU_PROVIDER=ec2` and
  `AI_ENABLE_REAL_GPU=1`. Targets exactly one configured instance id.

## 5. Configuration (added to `config.py`, all env-driven, safe defaults)

```
AI_ENABLED=1
AI_GPU_PROVIDER=mock            # mock | ec2
AI_ENABLE_REAL_GPU=0            # hard safety gate for the EC2 provider
AI_GPU_INSTANCE_ID=             # the g4dn.xlarge id (separate from the controller)
AI_GPU_REGION=ap-southeast-2
AI_JOB_DB_PATH=./data/ai_jobs.db
AI_QUEUE_BACKEND=sqlite         # sqlite | sqs
AI_S3_BUCKET=                   # empty => local dev storage
AI_USE_API_FALLBACK=0
AI_ALLOW_PAID_FALLBACK=0

# limits
AI_RATE_REQUESTS_PER_MINUTE=3
AI_MAX_PENDING_PER_USER=2
AI_MAX_DAILY_IMAGE_JOBS=20
AI_MAX_DAILY_VIDEO_JOBS=4
AI_MAX_DAILY_3D_JOBS=10
AI_MAX_GLOBAL_QUEUE=25
AI_MAX_GPU_ACTIVE_JOBS=1
AI_IDLE_GRACE_SECONDS=600
AI_MAX_GPU_SESSION_SECONDS=3600
AI_MAX_GPU_SECONDS_PER_DAY=21600
AI_MAX_GPU_SECONDS_PER_MONTH=200000
AI_BUDGET_MAX_USD=100          # software guard (NOT a substitute for AWS Budgets)

# timeouts
AI_IMAGE_INFERENCE_TIMEOUT_SECONDS=180
AI_GPU_STARTUP_TIMEOUT_SECONDS=600
AI_VIDEO_JOB_TIMEOUT_SECONDS=1200
AI_IMAGE_3D_JOB_TIMEOUT_SECONDS=600
```

## 6. Storage

```
objects/users/{user_id}/images/{job_id}.png
objects/users/{user_id}/videos/{job_id}.mp4
objects/users/{user_id}/models/{job_id}.glb
objects/users/{user_id}/loras/{lora_id}.safetensors
objects/model-cache/...        # separate from user data
```

- Dev: a private local directory served only via an ownership-checked route.
- Prod: private S3 with **short-lived presigned** GET/PUT; no public listing.
- Upload validation: size caps, extension + magic-byte checks, checksum.
- **Never** load user `.safetensors` as code; metadata is inspected, not executed.

## 7. Cost control

Software guard (`limits.py`) refuses to start the GPU when the daily/monthly/
total estimate is exhausted; AWS Budgets alerts are documented separately
(`docs/COST_GUARDRAILS.md`) because software limits ≠ billing alerts.

## 8. Phasing (this pass)

- Phase 0 ✅ audit + docs + infra templates.
- Phase 1 ✅ browser-only PNG/SVG→3D.
- Phase 2 ✅ job API + SQLite + mock lifecycle + tests (no AWS).
- Phase 3 ⏳ IAM/worker templates prepared; **deployment disabled pending approval**.
- Phases 4–7 ⏳ adapters scaffolded; require a real GPU + licence review.
