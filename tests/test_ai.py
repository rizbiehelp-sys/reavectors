"""
Tests for the AI Studio backend (Phase 2). No AWS, no GPU â€” the mock provider
drives the full lifecycle deterministically.

Run:  python tests/test_ai.py     (or)   python -m pytest tests/test_ai.py
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reavectors import config  # noqa: E402
from reavectors.ai import catalog, limits  # noqa: E402
from reavectors.ai.lifecycle import GPUManager, GPUState  # noqa: E402
from reavectors.ai.models import JobType, ValidationError, validate_request  # noqa: E402
from reavectors.ai.providers import MockGPUProvider  # noqa: E402
from reavectors.ai.service import AIService, _inspect_safetensors  # noqa: E402
from reavectors.ai.store import JobStore  # noqa: E402


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, d):
        self.t += d


def _make(clock=None, idle_grace=100, ready_after=0.0, generate_seconds=5.0):
    clock = clock or Clock()
    path = os.path.join(tempfile.mkdtemp(prefix="reatest_"), "jobs.db")
    store = JobStore(path, clock=clock)
    provider = MockGPUProvider(ready_after=ready_after, generate_seconds=generate_seconds, clock=clock)
    manager = GPUManager(provider, store, clock=clock, idle_grace=idle_grace, max_session=10_000)
    service = AIService(store, manager, clock=clock)
    return clock, store, provider, manager, service


def _img_params():
    return {"prompt": "a flat logo", "width": 512, "height": 512, "steps": 20}


# ---------------------------------------------------------------------------
def test_validate_request():
    assert validate_request("text_to_image", {"prompt": "x"}) == JobType.TEXT_TO_IMAGE
    for bad in (["nope", {}], ["text_to_image", {}],
                ["text_to_image", {"prompt": "x", "width": 99999}],
                ["text_to_image", {"prompt": "x", "steps": 999}],
                ["image_to_3d", {}]):
        try:
            validate_request(bad[0], bad[1]); assert False, f"expected error for {bad}"
        except ValidationError:
            pass


def test_store_idempotency():
    clock = Clock()
    _, store, *_ = _make(clock)
    a = store.create_job("u1", "text_to_image", "m", {}, idem_key="k1")
    b = store.create_job("u1", "text_to_image", "m", {}, idem_key="k1")
    c = store.create_job("u1", "text_to_image", "m", {}, idem_key="k2")
    assert a["id"] == b["id"] and a["id"] != c["id"], "idempotency key must dedupe"


def test_rate_limiter_and_limits():
    from reavectors.ai.limits import RateLimiter
    clock = Clock()
    lim = RateLimiter(limit=3, window=60, clock=clock)
    assert [lim.check("x") for _ in range(3)] == [0, 0, 0]
    assert lim.check("x") > 0, "4th call in the window must be limited"
    assert lim.check("y") == 0, "different key is independent"

    # per-user pending cap (default 2) rejects the 3rd pending submission
    _, store, _, _, service = _make(Clock())
    a = service.submit("u_pend", {"type": "text_to_image", "params": _img_params()})
    b = service.submit("u_pend", {"type": "text_to_image", "params": _img_params()})
    c = service.submit("u_pend", {"type": "text_to_image", "params": _img_params()})
    assert a[0] == 202 and b[0] == 202 and c[0] == 429, (a[0], b[0], c[0])


def test_lifecycle_single_start_and_completion():
    clock, store, provider, manager, service = _make(Clock())
    s1, j1 = service.submit("u1", {"type": "text_to_image", "params": _img_params()})
    s2, j2 = service.submit("u2", {"type": "text_to_image", "params": _img_params()})
    assert s1 == s2 == 202
    assert provider.started_calls == 1, "N simultaneous submits must produce ONE start"
    manager.pump()   # startup + dispatch job 1
    manager.pump()   # dispatch job 2
    assert store.get_job(j1["job_id"])["state"] == "succeeded"
    assert store.get_job(j2["job_id"])["state"] == "succeeded"
    # idle -> stop after grace
    clock.advance(101)
    manager.pump()
    assert provider.stopped_calls == 1 and manager.state == GPUState.STOPPED


def test_never_stop_while_queued():
    clock, store, provider, manager, service = _make(Clock())
    # 2 users x 2 jobs = 4 queued (per-user pending cap is 2)
    for u in ("a", "b"):
        service.submit(u, {"type": "text_to_image", "params": _img_params()})
        service.submit(u, {"type": "text_to_image", "params": _img_params()})
    manager.pump()                     # run one
    assert store.count_by_state(("created", "queued", "waking_gpu", "booting", "loading_model")) > 0
    clock.advance(1000)                # far past grace
    manager.pump()
    assert provider.stopped_calls == 0, "must not stop the GPU while work is queued"


def test_budget_guard_blocks_start():
    clock, store, provider, manager, service = _make(Clock())
    store.add_gpu_event("session", seconds=config.AI_MAX_GPU_SECONDS_PER_DAY + 1)
    assert limits.budget_ok(store, clock) is False
    job = store.create_job("u1", "text_to_image", "m", {})
    manager.kick(job)
    assert provider.started_calls == 0, "budget guard must block GPU start"


def test_safetensors_inspector():
    header = {"__metadata__": {}, "w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    blob = json.dumps(header).encode()
    data = struct.pack("<Q", len(blob)) + blob + b"\x00\x00\x00\x00"
    ok, meta = _inspect_safetensors(data)
    assert ok and meta["tensors"] == 1
    assert _inspect_safetensors(b"not a safetensors")[0] is False
    assert _inspect_safetensors(b"")[0] is False


def test_service_endpoints_and_ownership():
    clock, store, provider, manager, service = _make(Clock())
    st, obj = service.submit("alice", {"type": "text_to_image", "params": _img_params()},
                             idem_key="dup")
    assert st == 202
    jid = obj["job_id"]
    # idempotent resubmit returns the same job
    st2, obj2 = service.submit("alice", {"type": "text_to_image", "params": _img_params()},
                               idem_key="dup")
    assert st2 == 202 and obj2["job_id"] == jid
    # ownership: bob cannot read alice's job
    assert service.get("bob", jid)[0] == 404
    assert service.get("alice", jid)[0] == 200
    # capacity / models / loras
    assert service.capacity()[0] == 200
    assert service.models()[0] == 200
    assert service.loras("alice")[0] == 200
    # cancel while pending
    assert service.cancel("alice", jid)[0] == 200
    # lora upload: bad extension, then a valid safetensors
    assert service.upload_lora("alice", "x.bin", {}, b"x")[0] == 415
    header = {"__metadata__": {}, "w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    blob = json.dumps(header).encode()
    st, out = service.upload_lora("alice", "style.safetensors", {"name": "Style"},
                                  struct.pack("<Q", len(blob)) + blob + b"\x00\x00\x00\x00")
    assert st == 201 and out["lora"]["user_id"] == "alice"
    lid = out["lora"]["id"]
    assert service.delete_lora("bob", lid)[0] == 404     # cannot delete others'
    assert service.delete_lora("alice", lid)[0] == 200


def test_catalog_licenses_not_enabled_by_default():
    # Nothing is enabled in production until licences are verified.
    assert catalog.enabled_models() == []
    for m in catalog.models_for():
        assert m["enabled"] is False


def _patch_cfg(**kw):
    import reavectors.config as c
    old = {k: getattr(c, k) for k in kw}
    for k, v in kw.items():
        setattr(c, k, v)
    return old, c


def test_tripo_requires_secret_key():
    from reavectors.ai import tripo
    old, c = _patch_cfg(AI_TRIPO_API_KEY="tcli_abc123")
    try:
        try:
            tripo._require_key(); assert False, "client id must be rejected"
        except tripo.TripoAuthError:
            pass
        c.AI_TRIPO_API_KEY = ""
        try:
            tripo._require_key(); assert False, "empty key must be rejected"
        except tripo.TripoAuthError:
            pass
        c.AI_TRIPO_API_KEY = "tsk_ok"
        tripo._require_key()   # secret key accepted
    finally:
        for k, v in old.items():
            setattr(c, k, v)


def test_tripo_cost_guard_and_classify():
    from reavectors.ai import tripo
    tripo.check_cost(0.20)                       # under ceiling
    try:
        tripo.check_cost(5.00); assert False
    except tripo.TripoError:
        pass
    assert "credit" in tripo._classify(Exception("[2010] You don't have enough credit")).lower()


def test_tripo_fake_async_flow():
    import os
    from reavectors.ai import tripo
    old, c = _patch_cfg(AI_TRIPO_API_KEY="tsk_test", AI_ENABLE_TRIPO=True,
                        AI_TRIPO_MAX_USD_PER_JOB=1.0)

    class FakeTask:
        status = "success"

    class FakeClient:
        def __init__(self): self.created = None
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def image_to_model(self, **kw): self.created = kw; return "t1"
        async def wait_for_task(self, tid, **kw): return FakeTask()
        async def download_task_models(self, task, out):
            p = os.path.join(out, "model.glb")
            with open(p, "wb") as fh: fh.write(b"glTF\x02\x00\x00\x00")
            return {"pbr_model": p}

    holder = {}
    def factory():
        cl = FakeClient(); holder["c"] = cl; return cl
    try:
        res = tripo.generate_glb(b"png-bytes", "x.png", _client_factory=factory)
        assert res["glb"].startswith(b"glTF")
        assert holder["c"].created.get("model_version")   # version was sent
    finally:
        for k, v in old.items():
            setattr(c, k, v)

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
