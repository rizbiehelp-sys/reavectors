# AWS DEPLOYMENT (manual, disabled by default)

> **Nothing here runs automatically.** No `terraform apply`, no stack creation,
> no GPU provisioning. This code never touches your existing `t3.micro`
> (`i-007e647a0a3badac4`). Run each step manually and only after your approval.

## 0. Safety model in the running app

- `AI_GPU_PROVIDER=mock` (default) → all lifecycle calls are simulated. **No AWS.**
- `EC2Provider` is inert unless **both** `AI_GPU_PROVIDER=ec2` **and**
  `AI_ENABLE_REAL_GPU=1` are set, and it only ever `Describe/Start/Stop` the single
  instance in `AI_GPU_INSTANCE_ID`.
- IAM templates live in `infra/aws/` and are **least-privilege by design**.

## 1. Control plane (the existing t3.micro)

The same ReaVector package can run on the t3.micro as the controller. It is
lightweight: stdlib server + SQLite + boto3. Do **not** install ComfyUI/torch here.

```bash
# on the t3.micro (manual)
sudo apt-get update && sudo apt-get install -y python3 python3-venv git
git clone <your repo> && cd reavectors
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # vtracer wheels are manylinux; ok
cp .env.example .env                      # fill SUPABASE_* / AI_* (NO secrets in git)
python -m reavectors.server               # binds HOST/PORT
```

Keep it private; reach it via **Cloudflare Tunnel** (preferred) instead of opening
inbound ports. The controller needs the **`infra/aws/controller-iam-policy.json`**
policy attached to its instance role.

## 2. GPU worker — g4dn.xlarge (you create it manually)

**Do not do this automatically.** Recommended manual shape:

- AMI: Deep Learning Base OSS Nvidia Driver (Ubuntu) — or your own EBS-backed AMI.
- Instance: `g4dn.xlarge` in `ap-southeast-2` (Sydney) if quota/credits allow.
- **Persistent EBS** for model weights + HF cache (survives stop/start).
- IAM instance profile from **`infra/aws/gpu-worker-iam-policy.json`** (no keys).
- **No inbound public ports.** Admin via **SSM Session Manager**.
- Stop when idle (the lifecycle manager does this; verify it does).

Model weights live on EBS so a stop/start does not re-download them.

### Worker bootstrap (manual)

```bash
# run ON the GPU instance (see infra/aws/bootstrap-gpu-worker.sh)
sudo bash infra/aws/bootstrap-gpu-worker.sh
sudo systemctl enable --now reavectors-worker.service   # infra/aws/worker.service
```

The worker polls **SQS outbound** (no inbound), loads the requested model, runs
inference, uploads the result to **private S3**, and publishes a heartbeat with
`{state: ready|busy, model, vram_free}`.

## 3. Resources to create manually (order)

1. **S3** buckets: `reavectors-user-assets` (private), `reavectors-model-cache`
   (private, points at EBS-backed local cache). Block all public access.
2. **SQS**: `reavectors-jobs` + `reavectors-jobs-dlq` (dead-letter).
3. **IAM**: controller role + GPU worker role from the JSON templates.
4. **GPU instance** + instance profile + EBS.
5. **AWS Budgets** alert (see COST_GUARDRAILS.md) — do this **before** first GPU use.

## 4. Point the app at the real infrastructure (only when ready)

```ini
AI_GPU_PROVIDER=ec2
AI_ENABLE_REAL_GPU=1
AI_GPU_INSTANCE_ID=i-xxxxxxxxxxxxxxxxx     # the g4dn.xlarge, NOT the t3.micro
AI_QUEUE_BACKEND=sqs
AI_S3_BUCKET=reavectors-user-assets
AI_MAX_GPU_SESSION_SECONDS=3600
```

Set these as **env vars on the host** (never in git). Roll back by setting
`AI_GPU_PROVIDER=mock`.

## 5. Verification before enabling public use

- [ ] `DescribeInstances` returns exactly the intended GPU id.
- [ ] Two simultaneous submissions → **one** `StartInstances` call (check logs).
- [ ] Worker heartbeat required before any dispatch.
- [ ] Idle for `AI_IDLE_GRACE_SECONDS` → `StopInstances`; DB records the event.
- [ ] Budget guard blocks start at the configured ceiling.
- [ ] Restart recovery reconciles DB ↔ AWS state.
- [ ] Existing `/api/vectorize` still works (PNG→SVG unaffected).

## 6. Explicitly NOT done by this repository

- No instance creation, start, stop, resize or deletion on your behalf.
- No changes to the t3.micro.
- No spending of promotional credits.
- No paid fallback providers.
