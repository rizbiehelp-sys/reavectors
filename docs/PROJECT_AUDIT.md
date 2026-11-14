# PROJECT AUDIT — ReaVector (reavectors)

Phase 0 reconnaissance of the **actual** repository, before any AI Studio work.
Everything below was confirmed by inspecting the tree and source, not assumed.

## 1. Repository inventory

```
reavectors/
├── reavectors/            # Python package (stdlib, no web framework)
│   ├── server.py          # custom http.server: routes + SSE + hardening
│   ├── config.py          # all config from env (+ .env loader)
│   ├── security.py        # rate limiter, concurrency gate, upload validation, headers
│   ├── db.py              # optional Supabase log/stats (best-effort)
│   ├── vectorize.py       # PNG -> vector geometry (vtracer + potrace)
│   ├── refine.py          # time-budgeted closed-loop refiner
│   ├── vtracer_engine.py  # vtracer subprocess runner
│   ├── _vtracer_worker.py # isolated worker
│   ├── svgparse.py        # SVG path -> geometry (transforms included)
│   ├── export.py          # geometry -> PDF/AI/EPS
│   └── cli.py             # command line
├── web/                   # vanilla HTML/CSS/JS (no build step)
├── samples/  tests/  scripts/  .github/workflows/
├── Dockerfile  render.yaml  requirements.txt  .env.example
```

- **Frontend framework:** none. Vanilla ES modules (`web/app.js`) + `index.html` + `styles.css`.
- **Backend framework:** none. Python **`http.server.ThreadingHTTPServer`** with a hand-written `Handler`.
- **Language/runtime:** Python 3.12 (pinned `.python-version`), Node not required.
- **Tests:** `tests/test_reavectors.py` (stdlib test runner, no pytest dependency).

## 2. What exists and must be preserved

| Feature | Status | Notes |
|---|---|---|
| PNG → SVG/AI/PDF/EPS | **Production** | `POST /api/vectorize`, `POST /api/export` |
| Time-budgeted refinement | Production | `POST /api/refine` (SSE) |
| Stats (Supabase, optional) | Production | `GET /api/stats`, `GET /api/health` |
| Hardening | Production | rate limit, concurrency gate, CSP, upload validation |

The existing PNG→SVG controls, routes and behaviour **must not break**.

## 3. Existing conventions (reuse these)

- **Routing:** string-compare on `urlparse(self.path).path` inside `Handler.do_GET` / `do_POST`.
- **Responses:** `self._json(code, obj)` / `self._send(code, bytes, ctype)`; security headers on every response.
- **Errors:** `{"error": "..."}` JSON with the right status code.
- **Config:** every knob is an env var with a default, read in `config.py`.
- **Security:** per-IP sliding-window limiter, `heavy_gate` `BoundedSemaphore`, `validate_image()`, strict CSP.
- **Design system:** CSS variables in `web/styles.css` (`--accent`, `--panel`, cards, pills, spinner).

## 4. Gaps vs. the AI Studio spec

| Spec requirement | Current state | Decision |
|---|---|---|
| Accounts/auth | none | Add a lightweight session/user id now; plug into real auth later. Keep public mode working. |
| Persistent DB | none (Supabase optional) | Add **SQLite (WAL)** for the job registry — zero extra services, works on Render/t3.micro. |
| Job API | none | Add `/api/ai/*` to the existing server (no framework change). |
| SQS | none | Abstract behind a `Queue` interface: **in-process SQLite queue** now, SQS adapter later. |
| GPU lifecycle | none | Add a race-safe state machine with a **mock provider** (default) and a disabled boto3/EC2 adapter. |
| Browser 3D | none | Add `web/studio3d.html` + `web/studio3d.js` using **Three.js vendored locally** (CSP stays `script-src 'self'`). |
| LoRA library | none | Catalogue + upload endpoints (metadata only now; file storage behind an interface). |

## 5. Decisions and assumptions (documented)

1. **No framework migration.** The custom `http.server` is small, tested and hardened. FastAPI on the t3.micro is allowed by the spec *"only if a separate Python controller is necessary"* — it is not; the same package can run on the control plane.
2. **Frontend stays vanilla.** The spec forbids adding a large UI framework when a component system exists. Three.js is vendored under `web/vendor/` so CSP remains first-party.
3. **SQLite + WAL** for jobs/flags/usage. The spec explicitly allows "SQLite with WAL on persistent EBS for the initial lightweight job registry".
4. **Everything is mock-first.** Phases are testable with **no GPU and no AWS**: a `MockGPUProvider` drives the full lifecycle so the queue, API and state machine can be verified before any instance exists.
5. **AWS is prepared, never auto-applied.** IAM policies, bootstrap script and systemd unit are *templates*. No `terraform apply`, no instance creation, no start/stop calls are made by this work.
6. **Ranges/licensing are marked VERIFY.** No model licence or provider quota is asserted as fact (`docs/MODEL_LICENSES.md`).
7. **GPU stays off.** The lifecycle default provider is `mock`; the EC2 provider refuses to start unless `AI_GPU_PROVIDER=ec2` **and** an explicit enable flag are set.

## 6. Known infrastructure (provided, treated as external, untouched)

- Control plane: `t3.micro` `i-007e647a0a3badac4`, `ap-southeast-2b` — **must never be resized/stopped/deleted by this code**. The code only ever *describes* a *separate* configured GPU instance id.
- Target GPU: `g4dn.xlarge` (T4, ~16 GB VRAM) — **not assumed to exist**; referenced only by config, provider disabled by default.

## 7. Success criteria for this phase

- [x] Audit written from the real tree.
- [ ] Browser-only PNG/SVG→3D added without touching PNG→SVG.
- [ ] Job API + SQLite + mock lifecycle implemented and tested with **no** AWS/GPU.
- [ ] AWS/IAM/worker artefacts prepared as templates, deployment left disabled.
