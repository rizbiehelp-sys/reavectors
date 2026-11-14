"""
Rate limits, per-user quotas and the software cost guard.

All thresholds come from ``reavectors.config``. These are *software* guards; they
do not replace AWS Budgets alerts (see docs/COST_GUARDRAILS.md).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .. import config
from .models import JobType

# daily job caps per type
_DAILY = {
    JobType.TEXT_TO_IMAGE: lambda: config.AI_MAX_DAILY_IMAGE_JOBS,
    JobType.IMAGE_TO_VIDEO: lambda: config.AI_MAX_DAILY_VIDEO_JOBS,
    JobType.TEXT_TO_VIDEO: lambda: config.AI_MAX_DAILY_VIDEO_JOBS,
    JobType.IMAGE_TO_3D: lambda: config.AI_MAX_DAILY_3D_JOBS,
}


class LimitError(Exception):
    """Raised when a request must be rejected (→ HTTP 429/402/503)."""

    def __init__(self, message: str, status: int = 429):
        super().__init__(message)
        self.status = status
        self.message = message


class RateLimiter:
    """In-memory sliding window, per key (user id)."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.time):
        self.limit = max(1, int(limit))
        self.window = float(window)
        self.clock = clock
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        """Return retry-after seconds (0 = allowed)."""
        now = self.clock()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.limit:
                return max(1, int(self.window - (now - dq[0])))
            dq.append(now)
            return 0


def check_submit(store, user_id: str, job_type: JobType, limiter: RateLimiter) -> None:
    """Raise LimitError if this submission should be rejected."""
    retry = limiter.check(user_id)
    if retry:
        raise LimitError(f"rate limit: max {config.AI_RATE_REQUESTS_PER_MINUTE}/min", 429)

    if store.count_user_pending(user_id) >= config.AI_MAX_PENDING_PER_USER:
        raise LimitError(f"too many pending jobs (max {config.AI_MAX_PENDING_PER_USER})", 429)

    if store.count_by_state(["created", "queued", "waking_gpu", "booting", "loading_model"]
                            ) >= config.AI_MAX_GLOBAL_QUEUE:
        raise LimitError("global queue is full, try again shortly", 503)

    cap = _DAILY.get(job_type)
    if cap and store.count_user_day(user_id, job_type.value) >= cap():
        raise LimitError(f"daily limit reached for {job_type.value}", 429)


def budget_status(store, clock=time.time) -> dict:
    """Software cost guard: estimated GPU seconds/usd for day and month."""
    now = clock()
    day_start = now - (now % 86400)
    month_start = now - 30 * 86400
    day_s = store.gpu_seconds_since(day_start)
    month_s = store.gpu_seconds_since(month_start)
    est_usd = (month_s / 3600.0) * config.AI_GPU_USD_PER_HOUR
    return {
        "day_seconds": round(day_s, 1),
        "month_seconds": round(month_s, 1),
        "day_limit": config.AI_MAX_GPU_SECONDS_PER_DAY,
        "month_limit": config.AI_MAX_GPU_SECONDS_PER_MONTH,
        "est_usd_month": round(est_usd, 4),
        "budget_max_usd": config.AI_BUDGET_MAX_USD,
        "within_budget": (day_s < config.AI_MAX_GPU_SECONDS_PER_DAY
                          and month_s < config.AI_MAX_GPU_SECONDS_PER_MONTH
                          and est_usd < config.AI_BUDGET_MAX_USD),
        "note": "estimated from tracked GPU seconds — NOT AWS billing data",
    }


def budget_ok(store, clock=time.time) -> bool:
    return budget_status(store, clock)["within_budget"]
