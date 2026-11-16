"""
Owner-only on-demand Kaggle trigger (Kaggle Kernels API).

Turns "a job is queued" into "a private Kaggle GPU kernel starts now and works it":

    queue job -> trigger() -> `kaggle kernels push` (enable_gpu) ->
    kernel runs notebooks/kaggle_main.ipynb on a T4 ->
    pulls the job from the bridge, runs it, uploads the GLB.

Requires KAGGLE_USERNAME + KAGGLE_KEY (from kaggle.json) — stored only in env,
never committed. This is still personal/owner use; no public serving.

Not instant: Kaggle queues the kernel (minutes) and enforces a weekly GPU quota.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile

from .. import config

NOTEBOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "notebooks", "kaggle_main.ipynb")
BRIDGE_PLACEHOLDER = "PASTE_AI_BRIDGE_KEY_HERE"


class KaggleUnavailable(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.KAGGLE_USERNAME and config.KAGGLE_KEY)


def kernel_ref() -> str:
    return f"{config.KAGGLE_USERNAME}/{config.KAGGLE_KERNEL_SLUG}"


def _api():
    if not configured():
        raise KaggleUnavailable("Kaggle API not configured (KAGGLE_USERNAME/KAGGLE_KEY)")
    os.environ.setdefault("KAGGLE_USERNAME", config.KAGGLE_USERNAME)
    os.environ.setdefault("KAGGLE_KEY", config.KAGGLE_KEY)
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception as exc:  # noqa: BLE001
        raise KaggleUnavailable(f"kaggle package missing: {exc}") from exc
    api = KaggleApi()
    api.authenticate()
    return api


def build_kernel_dir(bridge_url: str, bridge_key: str, notebook_path: str = None) -> str:
    """Write a private kernel folder with the bridge key injected into the notebook."""
    src = notebook_path or NOTEBOOK
    if not os.path.isfile(src):
        raise KaggleUnavailable(f"notebook not found: {src}")
    with open(src, "r", encoding="utf-8") as f:
        nb = f.read()
    # inject secrets/config (the kernel is private)
    nb = nb.replace(BRIDGE_PLACEHOLDER, bridge_key)
    nb = nb.replace("os.environ.get('BRIDGE_URL', 'https://reavectors.onrender.com')",
                    repr(bridge_url))
    d = tempfile.mkdtemp(prefix="rv-kernel-")
    with open(os.path.join(d, "worker.ipynb"), "w", encoding="utf-8") as f:
        f.write(nb)
    meta = {
        "id": kernel_ref(),
        "title": "ReaVector Worker",
        "code_file": "worker.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    with open(os.path.join(d, "kernel-metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return d


def trigger(bridge_url: str, bridge_key: str, notebook_path: str = None) -> dict:
    api = _api()
    d = build_kernel_dir(bridge_url, bridge_key, notebook_path)
    try:
        api.kernels_push(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return {"kernel": kernel_ref(), "pushed": True, "url": f"https://www.kaggle.com/code/{kernel_ref()}"}


def status(ref: str = None) -> dict:
    api = _api()
    try:
        raw = api.kernels_status(ref or kernel_ref())
    except Exception as exc:  # noqa: BLE001
        raise KaggleUnavailable(f"status failed: {exc}") from exc
    # Kaggle returns datetimes/other objects -> make it plain JSON
    try:
        return json.loads(json.dumps(raw, default=str))
    except Exception:  # noqa: BLE001
        return {"raw": str(raw)}