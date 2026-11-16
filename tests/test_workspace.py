"""Tests for the Kaggle workspace: registry, scheduler, manifests."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors.ai import registry  # noqa: E402
from reavectors.ai.scheduler import DualGPUScheduler, VramError  # noqa: E402
from reavectors.ai.manifest import JobWorkspace, run_manifest  # noqa: E402


def test_registry_valid():
    assert registry.validate() == []


def test_registry_covers_tasks():
    tasks = {m.task for m in registry.REGISTRY}
    for t in registry.TASKS:
        assert t in tasks, f"no model for task {t}"


def test_live_adapters_exist():
    ids = {m.id for m in registry.adapters()}
    assert {"triposr", "sf3d"} <= ids


def test_gpu_placement():
    s = DualGPUScheduler()
    assert s.gpu_for("sdxl-base-1.0") == "0"
    assert s.gpu_for("ltx-video") == "1"
    assert s.gpu_for("triposr") == "1"


def test_vram_guard_refuses_hunyuan_on_t4():
    s = DualGPUScheduler(usable_vram={"0": 14.56, "1": 14.56})
    try:
        s.check("hunyuan3d-2.1", "1")
        assert False, "should refuse 24GB on a 14.56GB T4"
    except VramError:
        pass


def test_run_refuses_planned():
    s = DualGPUScheduler()
    try:
        s.run("sdxl-base-1.0", "x.png")
        assert False, "planned model must not run"
    except RuntimeError:
        pass


def test_scheduler_runs_live_adapter_with_fake():
    class FakeMgr:
        def run(self, adapter, inp, params, out):
            p = os.path.join(out, "model.glb")
            with open(p, "wb") as f:
                f.write(b"glb")
            return p
        def unload(self):
            pass

    s = DualGPUScheduler(manager_factory=lambda g: FakeMgr())
    d = tempfile.mkdtemp()
    p = s.run("triposr", "x.png", {}, d)
    assert p.endswith("model.glb") and os.path.isfile(p)


def test_manifest_and_workspace():
    ws = JobWorkspace(tempfile.mkdtemp(), "triposr")
    out = ws.save_output("a.glb", data=b"123")
    m = run_manifest("triposr", inputs={"image": "x.png"}, params={}, outputs=[out],
                     timings={"seconds": 1.0}, gpu="1")
    path = ws.write_manifest(m)
    assert os.path.isfile(path)
    assert m["model"]["id"] == "triposr"
    assert m["outputs"][0]["bytes"] == 3


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