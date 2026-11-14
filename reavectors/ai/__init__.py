"""
reavectors.ai — AI Studio job backend (mock-first, GPU off by default).

This package implements the queue-driven job API and the GPU lifecycle state
machine. It is fully testable **without any AWS or GPU**: the default provider is
a deterministic mock, and the EC2 provider refuses to act unless explicitly
enabled.
"""

from .models import JobType, JobState, TERMINAL_STATES
from .store import JobStore
from .lifecycle import GPUManager, GPUState
from .providers import MockGPUProvider, EC2Provider, build_provider
from .service import AIService, get_service

__all__ = [
    "JobType", "JobState", "TERMINAL_STATES",
    "JobStore", "GPUManager", "GPUState",
    "MockGPUProvider", "EC2Provider", "build_provider",
    "AIService", "get_service",
]
