"""Tests for the 3D AI Studio hosted client (no network, no credits)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors.ai.threedaistudio import ThreeDAIStudioClient, ThreeDAIStudioError  # noqa: E402


def _fake(calls):
    def t(method, url, payload):
        calls.append((method, url, payload))
        if url.endswith("/generate/pro/"):
            return 200, {"task_id": "task-1", "created_at": "2026-01-01T00:00:00Z"}
        return 200, {"status": "FINISHED", "progress": 100, "failure_reason": None,
                     "results": [{"asset": "https://storage.3daistudio.com/a.glb", "asset_type": "3D_MODEL"}]}
    return t


def test_submit_image():
    calls = []
    c = ThreeDAIStudioClient("k", transport=_fake(calls))
    r = c.submit_pro(image="data:image/png;base64,AAAA", model="3.1", enable_pbr=True)
    assert r["task_id"] == "task-1"
    method, url, payload = calls[0]
    assert method == "POST" and url.endswith("/v1/3d-models/tencent/generate/pro/")
    assert payload["image"].startswith("data:image/png")
    assert payload["model"] == "3.1" and payload["enable_pbr"] is True
    assert payload["generate_type"] == "Normal"


def test_status_parses_glb():
    calls = []
    c = ThreeDAIStudioClient("k", transport=_fake(calls))
    s = c.status("task-1")
    assert s["status"] == "FINISHED"
    assert s["results"][0]["asset_type"] == "3D_MODEL"
    assert s["results"][0]["asset"].endswith(".glb")


def test_multiview_omits_single_image():
    calls = []
    c = ThreeDAIStudioClient("k", transport=_fake(calls))
    c.submit_pro(multi_view=[{"view_type": "front", "view_image": "data:image/png;base64,AAAA"}])
    payload = calls[0][2]
    assert "image" not in payload and payload["multi_view_images"]


def test_missing_input_raises():
    c = ThreeDAIStudioClient("k", transport=_fake([]))
    try:
        c.submit_pro()
        assert False, "should require image/prompt/multi_view"
    except ThreeDAIStudioError:
        pass


def test_credit_estimate():
    assert ThreeDAIStudioClient.credits("3.1", True, False) == 80
    assert ThreeDAIStudioClient.credits("3.1", True, True) == 100
    assert ThreeDAIStudioClient.credits("3.1", False, False) == 60


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