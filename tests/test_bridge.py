"""Tests for the owner-only artifact bridge (no network)."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors.ai.bridge import ArtifactBridge  # noqa: E402


def test_full_flow():
    b = ArtifactBridge(tempfile.mkdtemp())
    job = b.submit("image2_3d", "triposr", "https://x/in.png", {"mc_resolution": 256})
    assert job["status"] == "pending"

    pend = b.list("pending")
    assert pend and pend[0]["id"] == job["id"]

    claimed = b.claim(job["id"])
    assert claimed["status"] == "claimed"
    assert b.claim(job["id"]) is None          # cannot double-claim

    res = b.complete(job["id"], "result.glb", b"GLBDATA", {"ok": True})
    assert res["artifact"].endswith(".glb")
    assert b.get(job["id"])["status"] == "done"
    assert b.artifact_path(res["artifact"]) is not None


def test_fail_marks_job():
    b = ArtifactBridge(tempfile.mkdtemp())
    job = b.submit("image2_3d", "sf3d")
    b.claim(job["id"])
    b.fail(job["id"], "boom")
    assert b.get(job["id"])["status"] == "failed"


def test_artifact_path_traversal_blocked():
    b = ArtifactBridge(tempfile.mkdtemp())
    assert b.artifact_path("../secret.glb") is None
    assert b.artifact_path("nope.glb") is None


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