"""
GPU provider adapters.

The default is :class:`MockGPUProvider` — deterministic, no AWS, used for all
testing. :class:`EC2Provider` is a real adapter that **refuses to act** unless
`AI_GPU_PROVIDER=ec2` AND `AI_ENABLE_REAL_GPU=1` AND an instance id are set. It
only ever describes/starts/stops that one instance; it never creates resources.
"""

from __future__ import annotations

import time
from typing import Protocol

from .. import config


class GPUProvider(Protocol):
    name: str

    def state(self) -> str: ...                 # "stopped" | "running" | ...
    def start(self) -> None: ...                # idempotent
    def stop(self) -> None: ...                 # idempotent
    def worker_ready(self) -> bool: ...          # model-loaded readiness
    def generate(self, job: dict) -> dict: ...   # -> {result_url, gpu_seconds}


class MockGPUProvider:
    """Simulated GPU: instant by default, optional start delay for tests."""

    name = "mock"

    def __init__(self, ready_after: float = 0.0, generate_seconds: float = 1.0, clock=time.time):
        self.clock = clock
        self.ready_after = float(ready_after)
        self.generate_seconds = float(generate_seconds)
        self._state = "stopped"
        self._started_at = None
        self.started_calls = 0
        self.stopped_calls = 0
        self.generated = 0

    def state(self) -> str:
        return self._state

    def start(self) -> None:
        if self._state != "running":
            self._state = "running"
            self._started_at = self.clock()
            self.started_calls += 1

    def stop(self) -> None:
        if self._state != "stopped":
            self._state = "stopped"
            self._started_at = None
            self.stopped_calls += 1

    def worker_ready(self) -> bool:
        return self._state == "running" and (self.clock() - self._started_at) >= self.ready_after

    def generate(self, job: dict) -> dict:
        self.generated += 1
        # The mock produces a tiny inline SVG placeholder (no real inference).
        return {
            "result_url": f"/api/ai/jobs/{job['id']}/result",
            "gpu_seconds": self.generate_seconds,
            "provider": self.name,
        }


class EC2Provider:
    """Real EC2 adapter. Inert unless explicitly enabled. Never creates resources."""

    name = "ec2"

    def __init__(self, instance_id: str = None, region: str = None, clock=time.time):
        self.clock = clock
        self.instance_id = instance_id or config.AI_GPU_INSTANCE_ID
        self.region = region or config.AI_GPU_REGION
        if config.AI_GPU_PROVIDER != "ec2" or not config.AI_ENABLE_REAL_GPU:
            raise RuntimeError("EC2 provider disabled (set AI_GPU_PROVIDER=ec2 and AI_ENABLE_REAL_GPU=1)")
        if not self.instance_id:
            raise RuntimeError("AI_GPU_INSTANCE_ID is not set")
        try:
            import boto3  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("boto3 is not installed") from exc
        import boto3
        self._ec2 = boto3.client("ec2", region_name=self.region)

    def state(self) -> str:
        r = self._ec2.describe_instances(InstanceIds=[self.instance_id])
        st = r["Reservations"][0]["Instances"][0]["State"]["Name"]
        return "running" if st == "running" else ("starting" if st in ("pending",) else "stopped")

    def start(self) -> None:
        if self.state() == "stopped":
            self._ec2.start_instances(InstanceIds=[self.instance_id])

    def stop(self) -> None:
        if self.state() == "running":
            self._ec2.stop_instances(InstanceIds=[self.instance_id])

    def worker_ready(self) -> bool:
        # Readiness comes from the worker heartbeat (SQS/S3), not EC2 state.
        return False

    def generate(self, job: dict) -> dict:
        # Real generation happens on the worker (SQS polled); the controller just
        # tracks state. This adapter is a skeleton until the worker exists.
        raise NotImplementedError("EC2 generation requires the GPU worker")


def build_provider(clock=time.time) -> GPUProvider:
    """Return the configured provider (mock unless ec2 is fully enabled)."""
    if config.AI_GPU_PROVIDER == "ec2":
        try:
            return EC2Provider(clock=clock)
        except RuntimeError:
            return MockGPUProvider(clock=clock)
    return MockGPUProvider(clock=clock)
