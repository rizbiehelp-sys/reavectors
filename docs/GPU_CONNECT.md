# Connect Kaggle + AWS GPU (on-demand) — step by step

The browser **Product 3D** tool is a fast *parametric* approximation (≈ 30 % match —
it measures the silhouette and wraps your exact label). The **90–98 %** result comes
from an **AI reconstruction model** running on a GPU. This guide connects that GPU
**on demand**: it starts only when a job is queued and stops when idle.

Nothing here is auto-run. Every AWS action is manual, and the app only *starts/stops
one instance you name* — it never creates resources.

---

## 0. Which model / which GPU

| Model | VRAM | Fits T4 (g4dn.xlarge)? | Licence | Notes |
|---|---|---|---|---|
| **TripoSR** | ~6 GB | ✅ | MIT | default, fastest, free |
| **SF3D** | ~6.5 GB | ✅ | Stability AI Community | better detail; <$1M revenue |
| **Hunyuan3D-2mini** | ~10 GB | ✅ (tight) | Tencent Hunyuan Community | mini quality bump |
| **Hunyuan3D-2.1** | ~24 GB | ❌ needs 24 GB | Tencent Hunyuan Community | **best quality** → `g5.xlarge`/`g6.xlarge` |

Recommendation: start on **`g4dn.xlarge` + SF3D** (cheap, good). Move to
**`g5.xlarge` + Hunyuan3D-2.1** only if you need Tripo-level fidelity.

---

## Part A — Kaggle (personal benchmarking only)

Kaggle is your free dual-T4 dev box. Kaggle's terms are **personal, non-commercial**;
**never** expose Kaggle sessions/tunnels to public ReaVector requests.

1. **Create the notebook** → *New Notebook* → Settings → Accelerator **GPU T4 ×2**
   (verify `!nvidia-smi` shows two Tesla T4).
2. **Get the code**
   ```bash
   !git clone https://github.com/rizbiehelp-sys/reavectors.git
   %cd reavectors
   !pip -q install numpy pillow trimesh
   ```
3. **Install the model you're benchmarking** (e.g. TripoSR):
   ```bash
   !git clone https://github.com/VAST-AI-Research/TripoSR /opt/TripoSR
   !pip -q install -r /opt/TripoSR/requirements.txt
   ```
4. **Benchmark each GPU separately** (watch their VRAM independently):
   ```bash
   !CUDA_VISIBLE_DEVICES=0 python bench/kaggle_benchmark.py --image data/product.png --models triposr,sf3d
   !CUDA_VISIBLE_DEVICES=1 python bench/kaggle_benchmark.py --image data/product.png --models hunyuan3d
   ```
   Each run writes `bench/results/benchmark-*.json` + a markdown table
   (model, version, licence, inference time, **peak VRAM**, resolution, quality notes).
5. **Decide the default** from the reports, then mirror it in production
   (`AI_3D_MODEL`). Kaggle is for *choosing*, AWS is for *serving*.

---

## Part B — AWS on-demand production GPU

### B1. Create the worker (once, by hand in the console)

1. **EBS volume** (persistent weights): EC2 → Volumes → *Create*, 100 GB `gp3`,
   same AZ as the instance → attach later at `/mnt/models`.
2. **IAM role**: EC2 → Roles → create from `infra/aws/gpu-worker-iam-policy.json`
   (SQS poll + S3 put + `ec2:StopInstances` on **its own** instance). No keys on the box.
3. **Launch instance**: `g4dn.xlarge` (or `g5.xlarge` for Hunyuan3D), **Deep Learning
   AMI (Ubuntu)**, attach the role, **no inbound Security Group rules**, access via
   **SSM Session Manager**.
4. **Attach + mount the EBS** and run the bootstrap once:
   ```bash
   sudo mkfs.ext4 /dev/nvme1n1 && sudo mkdir -p /mnt/models && sudo mount /dev/nvme1n1 /mnt/models
   cd /opt && sudo git clone https://github.com/rizbiehelp-sys/reavectors.git && cd reavectors
   sudo tee /etc/reavectors/worker.env >/dev/null <<EOF
   QUEUE_URL=<your SQS queue url>
   ASSETS_BUCKET=<your S3 bucket>
   AI_3D_MODEL=sf3d
   EOF
   sudo bash infra/aws/bootstrap-gpu-worker.sh
   sudo systemctl enable reavectors-worker.service
   ```
5. **Stop the instance** (EC2 → Stop). Baseline = **stopped** — it costs nothing idle.

### B2. Point the app at it (Render → Environment, never in git)

```
AI_GPU_PROVIDER=ec2
AI_ENABLE_REAL_GPU=1
AI_GPU_INSTANCE_ID=i-xxxxxxxx
AI_GPU_REGION=ap-southeast-2
AI_IDLE_GRACE_SECONDS=600
AI_MAX_GPU_SESSION_SECONDS=3600
AI_MAX_GPU_SECONDS_PER_DAY=21600
AI_MAX_GPU_SECONDS_PER_MONTH=200000
AI_BUDGET_MAX_USD=100
AI_GPU_USD_PER_HOUR=0.53
```

### B3. On-demand behaviour (already implemented)

- First queued job → `lifecycle.kick()` starts the GPU **once** (one start per idle
  period, guarded by a lock; N simultaneous submits = 1 start).
- Worker polls **SQS** (outbound only), runs the model, uploads the `.glb` to **S3**.
- No queued/running work for `AI_IDLE_GRACE_SECONDS` (600 s) → the app **stops** the
  instance. It **never** stops mid-work.
- Budget caps (`PER_DAY`/`PER_MONTH`/`BUDGET_MAX_USD`) reject new jobs before they can
  start the GPU.

### B4. Kill switch

Set `AI_ENABLE_REAL_GPU=0` (and/or `AI_GPU_PROVIDER=mock`) → the app instantly stops
touching AWS. Default is already **off**.

---

## Part C — Verify

1. Submit one Product 3D / job from the app.
2. EC2 console: the instance goes **running** within a minute; `sudo systemctl status
   reavectors-worker` shows the model loading.
3. The job result lands in S3 and appears in the app.
4. Leave it idle ~10 min → EC2 shows **stopped** (idle-grace stop).

---

## Costs (why on-demand)

`g4dn.xlarge` ≈ **$0.53/hr**. 30 min/day ≈ **$8/month**; 0 idle minutes ≈ **$0**.
The instance runs **only** while jobs are flowing.
