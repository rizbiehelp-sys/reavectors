"""Tests for the Kaggle on-demand trigger (no network, no push)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors.ai import kaggle_runner  # noqa: E402


def test_build_kernel_dir_injects_key_and_gpu():
    d = kaggle_runner.build_kernel_dir("https://bridge.example", "SECRETKEY123")
    try:
        meta_path = os.path.join(d, "kernel-metadata.json")
        nb_path = os.path.join(d, "worker.ipynb")
        assert os.path.isfile(meta_path) and os.path.isfile(nb_path)
        meta = json.load(open(meta_path, encoding="utf-8"))
        assert meta["enable_gpu"] is True
        assert meta["is_private"] is True
        assert meta["kernel_type"] == "notebook"
        assert meta["code_file"] == "worker.ipynb"
        nb = open(nb_path, encoding="utf-8").read()
        assert "SECRETKEY123" in nb
        assert "bridge.example" in nb
        assert "PASTE_AI_BRIDGE_KEY_HERE" not in nb
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_kernel_ref_shape():
    ref = kaggle_runner.kernel_ref()
    assert "/" in ref and ref.split("/")[1]


def test_configured_reflects_config():
    saved = (kaggle_runner.config.KAGGLE_USERNAME, kaggle_runner.config.KAGGLE_KEY)
    try:
        kaggle_runner.config.KAGGLE_USERNAME = ""
        kaggle_runner.config.KAGGLE_KEY = ""
        assert kaggle_runner.configured() is False
        try:
            kaggle_runner.trigger("https://x", "k")
            assert False, "should refuse without credentials"
        except kaggle_runner.KaggleUnavailable:
            pass
    finally:
        kaggle_runner.config.KAGGLE_USERNAME, kaggle_runner.config.KAGGLE_KEY = saved


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_all())