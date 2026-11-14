"""Job domain model: types, states, and validation rules."""

from __future__ import annotations

from enum import Enum


class JobType(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_VIDEO = "image_to_video"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_3D = "image_to_3d"


class JobState(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    WAKING_GPU = "waking_gpu"
    BOOTING = "booting"
    LOADING_MODEL = "loading_model"
    RUNNING = "running"
    SAVING_RESULT = "saving_result"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATES = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.TIMED_OUT}

# Which job types require the GPU worker (everything except browser extrusion).
GPU_JOB_TYPES = {JobType.TEXT_TO_IMAGE, JobType.IMAGE_TO_VIDEO, JobType.TEXT_TO_VIDEO, JobType.IMAGE_TO_3D}

# Per-type limits applied to user input (sane, configurable later).
LIMITS = {
    JobType.TEXT_TO_IMAGE: {"prompt_max": 2000, "max_side": 1024, "steps_max": 60},
    JobType.IMAGE_TO_VIDEO: {"prompt_max": 1000, "max_seconds": 6},
    JobType.TEXT_TO_VIDEO: {"prompt_max": 2000, "max_seconds": 6},
    JobType.IMAGE_TO_3D: {"max_side": 2048},
}


class ValidationError(ValueError):
    """Raised when a job request is invalid (maps to HTTP 400/422)."""


def validate_request(job_type: str, params: dict) -> "JobType":
    """Validate an incoming job request and return its JobType."""
    try:
        jt = JobType(job_type)
    except ValueError:
        raise ValidationError(f"unknown job type: {job_type!r}")

    params = params or {}
    lim = LIMITS[jt]

    if jt in (JobType.TEXT_TO_IMAGE, JobType.TEXT_TO_VIDEO):
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            raise ValidationError("prompt is required")
        if len(prompt) > lim["prompt_max"]:
            raise ValidationError(f"prompt too long (max {lim['prompt_max']})")

    if jt == JobType.TEXT_TO_IMAGE:
        for key, cap in (("width", lim["max_side"]), ("height", lim["max_side"])):
            v = params.get(key)
            if v is not None and (not isinstance(v, int) or v < 64 or v > cap):
                raise ValidationError(f"{key} must be an integer 64..{cap}")
        steps = params.get("steps")
        if steps is not None and (not isinstance(steps, int) or not 1 <= steps <= lim["steps_max"]):
            raise ValidationError(f"steps must be 1..{lim['steps_max']}")

    if jt in (JobType.IMAGE_TO_VIDEO, JobType.IMAGE_TO_3D):
        if not params.get("input_ref"):
            raise ValidationError("input_ref (uploaded image) is required")

    if jt in (JobType.IMAGE_TO_VIDEO, JobType.TEXT_TO_VIDEO):
        secs = params.get("seconds")
        if secs is not None and (not (isinstance(secs, (int, float))) or not 1 <= secs <= lim["max_seconds"]):
            raise ValidationError(f"seconds must be 1..{lim['max_seconds']}")

    return jt
