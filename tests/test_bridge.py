"""Tests for the bridge (local + Supabase-storage backends, no network)."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors.ai.bridge import ArtifactBridge, SupabaseBridge  # noqa: E402


def test_local_full_flow():
    b = ArtifactBridge(tempfile.mkdtemp())
    job = b.submit("image2_3d", "triposr", "https://x/in.png", {})
    assert b.list("pending")[0]["id"] == job["id"]
    assert b.claim(job["id"])["status"] == "claimed"
    assert b.claim(job["id"]) is None
    res = b.complete(job["id"], "r.glb", b"GLB")
    assert b.get(job["id"])["status"] == "done"
    assert b.artifact_bytes(res["artifact"]) == b"GLB"


def test_local_traversal_blocked():
    b = ArtifactBridge(tempfile.mkdtemp())
    assert b.artifact_bytes("../secret") is None
    assert b.artifact_bytes("missing.glb") is None


class FakeStore:
    def __init__(self):
        self.objs = {}

    def __call__(self, method, path, data=None, headers=None):
        if path == "/bucket":
            return 200, b'{"ok": true}'
        if path.startswith("/object/list/"):
            prefix = json.loads(data)["prefix"]
            return 200, json.dumps([{"name": n} for n in self.objs if n.startswith(prefix)]).encode()
        if path.startswith("/object/"):
            name = path.split("/object/", 1)[1].split("/", 1)[1]
            if method == "POST":
                self.objs[name] = data
                return 200, b'{"Key": ""}'
            return (200, self.objs[name]) if name in self.objs else (400, b"")
        return 404, b""


def test_supabase_flow():
    store = FakeStore()
    b = SupabaseBridge("https://x.supabase.co", "svc-key", "ai-bridge", transport=store)
    assert b.backend == "supabase"
    job = b.submit("image2_3d", "sf3d", "https://x/in.png")
    assert b.list("pending")[0]["id"] == job["id"]
    assert b.claim(job["id"])["status"] == "claimed"
    res = b.complete(job["id"], "m.glb", b"GLBDATA")
    assert res["artifact"] == "art_" + job["id"] + ".glb"
    assert b.get(job["id"])["status"] == "done"
    assert b.artifact_bytes(res["artifact"]) == b"GLBDATA"
    b.fail(job["id"], "x"); assert b.get(job["id"])["status"] == "failed"


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
