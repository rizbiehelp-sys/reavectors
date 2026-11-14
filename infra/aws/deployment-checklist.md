# AWS Deployment Checklist (manual)

Everything is **manual and disabled by default**. Nothing in this repo creates,
starts, stops or bills AWS resources on its own.

## Pre-flight

- [ ] Confirm GPU quota for `g4dn.xlarge` in `ap-southeast-2` (Service Quotas → EC2).
- [ ] Confirm promotional credits cover EC2 + EBS + SQS + S3 (verify, don't assume).
- [ ] Create the **AWS Budget** (see `docs/COST_GUARDRAILS.md`) *before* any GPU use.
- [ ] Decide/record the EBS volume for model weights (persistent, survives stop).

## Create resources (console or CLI, by hand)

- [ ] S3 `reavectors-user-assets` (private, block public access).
- [ ] S3 `reavectors-model-cache` (private).
- [ ] SQS `reavectors-jobs` + `reavectors-jobs-dlq`.
- [ ] SQS `reavectors-heartbeat`.
- [ ] IAM role/policy for the controller → `infra/aws/controller-iam-policy.json`.
- [ ] IAM role/policy for the worker → `infra/aws/gpu-worker-iam-policy.json`.
- [ ] Launch `g4dn.xlarge` with the worker profile + persistent EBS; **no inbound ports**.
- [ ] Attach the controller policy to the **existing t3.micro** role (do not modify the instance itself).

## Worker

- [ ] Copy the repo to the instance, run `infra/aws/bootstrap-gpu-worker.sh`.
- [ ] `sudo systemctl enable --now reavectors-worker.service`.
- [ ] Verify heartbeat appears and `worker_ready` flips true.

## App configuration (host env, never git)

- [ ] `AI_GPU_PROVIDER=ec2`, `AI_ENABLE_REAL_GPU=1`, `AI_GPU_INSTANCE_ID=<g4dn id>`.
- [ ] `AI_QUEUE_BACKEND=sqs`, `AI_S3_BUCKET=reavectors-user-assets`.
- [ ] `AI_MAX_GPU_SESSION_SECONDS`, idle grace, daily/monthly caps set.
- [ ] `AI_USE_API_FALLBACK=0`, `AI_ALLOW_PAID_FALLBACK=0`.

## Verification (before public use)

- [ ] Two simultaneous submits → exactly **one** `StartInstances`.
- [ ] No dispatch until worker `ready` heartbeat.
- [ ] Idle `AI_IDLE_GRACE_SECONDS` → `StopInstances` recorded in DB.
- [ ] Budget guard blocks start at the ceiling.
- [ ] Controller restart reconciles DB ↔ AWS state; orphaned jobs requeued.
- [ ] Result objects are private; a user cannot fetch another user's object.
- [ ] `/api/vectorize` (PNG→SVG) still works.

## Rollback

- [ ] Set `AI_GPU_PROVIDER=mock` and redeploy → all GPU calls stop; no instance touched.
- [ ] Manually stop the GPU instance if needed.
