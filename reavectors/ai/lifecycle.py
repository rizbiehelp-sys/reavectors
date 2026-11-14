"""
Race-safe GPU lifecycle manager.

```
STOPPED → STARTING → BOOTING → INITIALIZING → READY → BUSY → IDLE_GRACE → STOPPING → STOPPED
```

Guarantees:
* **One start per idle period.** ``kick()`` is guarded by a lock and only calls
  ``provider.start()`` when the state is ``STOPPED``; N simultaneous submits
  produce exactly one start.
* **Readiness ≠ "EC2 running".** Dispatch waits for ``provider.worker_ready()``.
* **Never stop mid-work.** Idle stop requires no queued and no running job.
* ``pump()`` advances the machine (called by a background thread in the app, or
  directly in tests). It is deterministic and AWS-free with the mock provider.
"""

from __future__ import annotations

import threading
import time
from enum import Enum

from .. import config
from . import limits


class GPUState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    BOOTING = "booting"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    IDLE_GRACE = "idle_grace"
    STOPPING = "stopping"


PENDING_STATES = ("created", "queued", "waking_gpu", "booting", "loading_model")


class GPUManager:
    def __init__(self, provider, store, clock=time.time,
                 idle_grace: int = None, max_session: int = None, max_active: int = None):
        self.provider = provider
        self.store = store
        self.clock = clock
        self.idle_grace = config.AI_IDLE_GRACE_SECONDS if idle_grace is None else idle_grace
        self.max_session = config.AI_MAX_GPU_SESSION_SECONDS if max_session is None else max_session
        self.max_active = config.AI_MAX_GPU_ACTIVE_JOBS if max_active is None else max_active
        self._lock = threading.Lock()
        self.state = GPUState.STOPPED
        self.last_activity = clock()
        self.session_started = None

    # ---- external actions ----------------------------------------------
    def kick(self, job: dict = None) -> None:
        """Called when a job is queued: start the GPU once, if stopped."""
        with self._lock:
            self.last_activity = self.clock()
            if job is not None and job.get("state") in ("created",):
                self.store.set_state(job["id"], "queued")
            if self.state == GPUState.STOPPED:
                if not limits.budget_ok(self.store, self.clock):
                    # Job stays queued; it will be rejected by the API before this.
                    return
                self.provider.start()
                self.store.add_gpu_event("start", instance=getattr(self.provider, "instance_id", ""))
                self.state = GPUState.STARTING
                self.session_started = self.clock()
                if job is not None:
                    self.store.set_state(job["id"], "waking_gpu")

    def pump(self) -> None:
        """Advance the state machine one step."""
        with self._lock:
            now = self.clock()
            if self.state == GPUState.STOPPED:
                return

            # startup progression
            if self.state in (GPUState.STARTING, GPUState.BOOTING, GPUState.INITIALIZING):
                if self.provider.state() == "running":
                    self.state = GPUState.BOOTING
                if self.provider.worker_ready():
                    self.state = GPUState.READY

            # dispatch while ready/busy
            if self.state in (GPUState.READY, GPUState.BUSY):
                if self.store.running_count() < self.max_active:
                    job = self.store.next_queued()
                    if job:
                        self._run(job, now)

            # idle / session-cap shutdown
            if self.state in (GPUState.READY, GPUState.BUSY, GPUState.IDLE_GRACE):
                idle = self.store.count_by_state(PENDING_STATES) == 0 and self.store.running_count() == 0
                if idle:
                    over_grace = (now - self.last_activity) >= self.idle_grace
                    over_session = self.session_started is not None and (now - self.session_started) >= self.max_session
                    if over_grace or over_session:
                        self._stop(reason="session_cap" if over_session and not over_grace else "idle")

    def force_stop(self) -> None:
        with self._lock:
            if self.state != GPUState.STOPPED:
                self._stop(reason="manual")

    # ---- internals ------------------------------------------------------
    def _run(self, job: dict, now: float) -> None:
        self.state = GPUState.BUSY
        self.store.set_state(job["id"], "running", provider=self.provider.name)
        try:
            res = self.provider.generate(job)
        except Exception as exc:  # noqa: BLE001 - worker/model failure
            self.store.set_state(job["id"], "failed", error=f"{type(exc).__name__}: {exc}")
        else:
            self.store.add_gpu_event("session", seconds=res.get("gpu_seconds", 0.0),
                                     instance=getattr(self.provider, "instance_id", ""))
            self.store.set_state(job["id"], "succeeded",
                                 result_url=res.get("result_url"),
                                 gpu_seconds=res.get("gpu_seconds", 0.0),
                                 provider=res.get("provider", self.provider.name))
        self.last_activity = now
        self.state = GPUState.READY

    def _stop(self, reason: str = "idle") -> None:
        self.state = GPUState.STOPPING
        self.provider.stop()
        self.store.add_gpu_event("stop", instance=getattr(self.provider, "instance_id", ""))
        self.state = GPUState.STOPPED
        self.session_started = None

    # ---- introspection --------------------------------------------------
    def status(self) -> dict:
        return {
            "gpu_state": self.state.value,
            "provider": self.provider.name,
            "real_gpu_enabled": bool(config.AI_ENABLE_REAL_GPU and config.AI_GPU_PROVIDER == "ec2"),
            "last_activity": round(self.last_activity, 1),
            "session_seconds": round(self.clock() - self.session_started, 1) if self.session_started else 0,
            "idle_grace_seconds": self.idle_grace,
            "max_session_seconds": self.max_session,
        }
