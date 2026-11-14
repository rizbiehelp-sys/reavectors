# IMPLEMENTATION LOG — ReaVector AI Studio

Running log of what is **implemented, tested, deployed** vs **prepared but needs
manual AWS approval**. Kept current as decisions change.

## Environment

- Live: https://reavectors.onrender.com (Render, Python 3.12, free/keep-alive cron).
- Repo: https://github.com/rizbiehelp-sys/reavectors
- Control plane (provided, **untouched**): t3.micro `i-007e647a0a3badac4`, `ap-southeast-2b`.
- GPU (target, **not assumed to exist**): g4dn.xlarge — referenced only by config.

## Phase 0 — audit + design ✅ DONE

- `docs/PROJECT_AUDIT.md` — real repo inventory (stdlib Python server + vanilla JS,
  no framework/auth/DB). Decisions recorded.
- `docs/AI_STUDIO_ARCHITECTURE.md`, `docs/MODEL_LICENSES.md`,
  `docs/AWS_DEPLOYMENT.md`, `docs/COST_GUARDRAILS.md`.
- `infra/aws/` — controller + worker IAM policies, worker bootstrap script,
  systemd unit, deployment checklist. **No credentials; nothing auto-applies.**

## Phase 1 — browser-only PNG/SVG → 3D ✅ DONE

- `web/studio3d.html` + `web/studio3d.js` (three.js vendored under
  `web/vendor/three/`, relative imports so CSP stays `script-src 'self'`).
- Features: transparent PNG (vectorised first via the existing CPU vectorizer) or
  SVG input; depth + bevel controls; color/metalness/roughness; wireframe; grid;
  background; orbit/zoom/pan; reset camera; **GLB export**.
- **No GPU**: this tool never touches the job queue or AWS.
- Verified: modules served with correct MIME, ESM syntax checks pass, page + assets
  return 200 live. (Visual browser rendering to be eye-checked by you.)
- Existing PNG→SVG left untouched and verified live afterwards (engine=vtracer).

## Phase 2 — controller + job queue (mock) ✅ DONE

- `reavectors/ai/` — `store.py` (SQLite/WAL job registry, quotas, GPU usage,
  LoRA catalogue), `models.py` (types/states/validation), `limits.py`
  (rate limits + cost guard), `lifecycle.py` (race-safe GPU state machine),
  `providers.py` (mock + guarded EC2 adapter), `catalog.py`, `service.py`,
  `worker.py` (inert skeleton for systemd).
- Routes added to the existing server: `/api/ai/jobs`, `/api/ai/jobs/{id}`,
  `/api/ai/jobs/{id}/cancel`, `/api/ai/jobs/history`, `/api/ai/capacity`,
  `/api/ai/models`, `/api/ai/loras`, `/api/ai/loras/upload`, `/api/ai/loras/{id}`.
- Guarantees implemented: **one GPU start per idle period** (lock-guarded),
  readiness gate (not "EC2 running"), idle shutdown that never stops work in
  flight, idempotency keys, per-user quota + rate limits, ownership checks,
  budget guard blocks start, safetensors metadata inspection (no code execution).
- **Tests: 9/9 pass** (`tests/test_ai.py`), **no AWS/GPU required**. Existing
  suite still **16/16** (`tests/test_reavectors.py`).
- Live check: submit → `202` + `waking_gpu` → background pump → `succeeded`;
  idempotent replay returns the same `job_id`; capacity shows mock GPU + budget.

## Phase 3 — AWS GPU lifecycle ⏳ PREPARED, DISABLED

Code + templates exist (EC2 adapter, IAM policies, bootstrap, systemd unit,
checklist). **Nothing is applied.** To enable you must, manually:

1. Create S3 buckets + SQS queues + IAM roles (`infra/aws/*.json`).
2. Launch `g4dn.xlarge` with the worker profile + persistent EBS (weights).
3. Run `infra/aws/bootstrap-gpu-worker.sh` and the systemd unit on the instance.
4. Set `AI_GPU_PROVIDER=ec2`, `AI_ENABLE_REAL_GPU=1`, `AI_GPU_INSTANCE_ID=…`,
   `AI_QUEUE_BACKEND=sqs`, `AI_S3_BUCKET=…` as **host env vars** (never in git).
5. Run the verification list in `infra/aws/deployment-checklist.md`.
Until then, the app stays on the **mock** provider and makes **no** AWS calls.

## Phases 4–7 — SDXL/LoRA, TripoSR, video ⏳ NOT STARTED

Adapters are scaffolded (catalogue entries, job types, timeouts, quotas). Each
model must pass the licence checklist (`docs/MODEL_LICENSES.md`) and a real T4
benchmark before being enabled. `catalog.enabled_models()` is empty by design.

## Known limitations

- No user accounts yet: identity is `X-User-Id` or an anonymous IP hash. Plug in
  the real auth provider when available.
- The Render filesystem is ephemeral → the production job DB belongs on the
  t3.micro EBS (set `AI_JOB_DB_PATH`). On Render it is per-instance.
- `worker.py` is inert until inference adapters + SQS wiring exist.
- EC2 provider `worker_ready()` is stubbed (needs the worker heartbeat channel).
- Model licences and provider quotas are **unverified** (marked VERIFY).
