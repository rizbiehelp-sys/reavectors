# COST GUARDRAILS

Two independent layers. **Software limits are not a substitute for AWS billing
alerts** — you need both.

## 1. In-app software guard (`reavectors/ai/limits.py`)

Enforced **before** any GPU start:

| Setting | Default | Meaning |
|---|---|---|
| `AI_MAX_GPU_SECONDS_PER_DAY` | 21600 (6 h) | summed GPU running seconds today |
| `AI_MAX_GPU_SECONDS_PER_MONTH` | 200000 (~55 h) | summed GPU seconds this month |
| `AI_MAX_GPU_SESSION_SECONDS` | 3600 | max single continuous session |
| `AI_BUDGET_MAX_USD` | 100 | estimated spend ceiling (credits) |
| `AI_IDLE_GRACE_SECONDS` | 600 | stop after idle |
| `AI_MAX_GLOBAL_QUEUE` | 25 | reject beyond queue cap (429) |

The guard refuses to start the GPU when any ceiling is reached and returns a
clear error (never silently switches to a paid provider).

**Estimated cost** uses a configurable hourly rate (`AI_GPU_USD_PER_HOUR`,
default ≈ the g4dn.xlarge on-demand ballpark). This is an **estimate for the
dashboard**, explicitly labelled "estimated — not AWS billing data".

Usage is persisted in SQLite (`gpu_usage` table) and reconciled against the real
instance state on each controller restart.

## 2. AWS Budgets (do this before first GPU use — manual)

Console → **Billing → Budgets → Create budget → Cost budget**:

1. Period: Monthly.
2. Amount: set a **hard** ceiling below your credit (e.g. `$20` initially even
   with $100 credits, so an error is caught early).
3. Alerts:
   - **ACTUAL** at 50 / 80 / 100 % → email you.
   - **FORECASTED** at 100 % → email you.
4. (Optional) Budget action → stop/notify on breach.

Also:

- Enable **Cost Anomaly Detection** (free) for `EC2` service.
- Tag GPU resources `Project=reavectors`, alert on that tag.
- Consider an **AWS Cost Category** so GPU spend is separable from the t3.micro.

## 3. Structural savings

- **Scale to zero**: instance is `stopped` when idle (EBS-only cost retains
  weights). Auto-stop after `AI_IDLE_GRACE_SECONDS`.
- **Single worker** first (`AI_MAX_GPU_ACTIVE_JOBS=1`) → no fan-out cost.
- **Queue caps + per-user daily caps** stop a runaway loop from repeatedly
  cold-starting the GPU.
- **Idempotency keys** prevent accidental double generations (double cost).
- Video/3D have their **own** daily caps and longer timeouts — the most expensive
  jobs are the most strictly limited.

## 4. What is intentionally NOT done

- No auto-provisioning, no instance type changes, no paid fallbacks.
- No "artificial activity" to keep sessions/credits alive.
- No assumption that credits cover every AWS service.
