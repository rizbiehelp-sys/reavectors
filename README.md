# reavectors

A local, offline **transparent PNG → vector** converter. Drop a PNG, get clean
editable geometry out as **SVG**, **AI** (Illustrator, PDF-compatible), **PDF**,
or **EPS**. Runs entirely on your machine — the image only ever goes to a
loopback server.

Original implementation built from open components. It shares no code, model, or
assets with any third party.

```
    transparent PNG  ──▶  reavectors  ──▶  .svg / .ai / .pdf / .eps
```

## Two engines

| Engine | What it is | Best for |
|---|---|---|
| **`vtracer`** (default) | visioncortex's modern **multi-colour** vectoriser, run out-of-process | logos, stickers, flat art, gradients, general images — **best quality** |
| `potrace` | classic Potrace applied to one flat mask per palette colour | crisp two-tone line art, cut files, deterministic flat output |

`engine="auto"` uses vtracer when available and transparently falls back to
Potrace if vtracer is missing or fails on an input.

## How it works

1. **Alpha = silhouette.** Pixels below the alpha cutoff are ignored, so the
   transparent background is never drawn and the output stays transparent.
2. **Trace.**
   - *vtracer*: clusters colours and fits smooth Bézier outlines per colour
     layer (a genuine colour vectoriser).
   - *potrace*: quantises to a flat palette, traces one binary mask per colour.
3. **Serialise.** The engine's SVG is preserved verbatim; its geometry is also
   parsed (see `svgparse.py`) so the **same paths** can be written to PDF/AI and
   EPS. No background rectangle is ever added.

## Install

```powershell
pip install -r requirements.txt      # vtracer, potracer, Pillow, numpy
```

## CLI

```powershell
python -m reavectors logo.png -o logo.svg
python -m reavectors logo.png --format svg,ai,pdf,eps --outdir out
python -m reavectors photo.png --style photo --format svg    # gradients
python -m reavectors line.png --engine potrace --format svg  # two-tone
```

| Option | Default | Meaning |
|---|---|---|
| `--engine` | auto | `auto` \| `vtracer` \| `potrace` |
| `--style` | logo | vtracer preset: `logo` (flat) \| `photo` (gradients) \| `line` (two-tone) |
| `--detail` | 16 | vtracer `layer_difference` (smaller = more colour layers / detail) |
| `--colors` | 8 | potrace palette size 1–256 |
| `--alpha-threshold` | 128 | alpha cutoff 0–255 |
| `--turdsize` | 2 | potrace: drop specks smaller than N px |
| `--alphamax` | 1.0 | potrace corner threshold (0–1.334) |
| `--opttolerance` | 0.2 | potrace curve-optimisation tolerance |
| `--max-size` | 1600 | downscale longest edge before tracing (0 = off) |
| `--refine` | 0 | spend up to N seconds refining for more detail (e.g. `10`) |

## Web app

```powershell
python -m reavectors.server        # open http://127.0.0.1:8756
```

Drag a PNG in (or paste with Ctrl+V), pick a **Style**, **gradient detail**, and
optionally tick **Refine** (up to N seconds for more detail), then download
`.svg`, `.ai`, or `.eps`. The preview sits on a checkerboard so the preserved
transparency is obvious, and the status line reports the refinement passes and
the achieved match %.

### HTTP API

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/` | — | the web UI |
| `POST` | `/api/vectorize?engine=auto&style=logo&detail=16` | image bytes | JSON `{svg, engine, width, height, colors, figures, subpaths, palette}` |
| `POST` | `/api/export?format=ai&name=logo&...` | image bytes | the file (`ai`/`pdf`/`eps`/`svg`) |

## Output notes

- **SVG** — engine-native SVG, transparent background.
- **AI** — a **PDF-compatible** file, written with **ReportLab** so it is a
  fully-formed PDF (correct `/Resources`, `/ProcSet`, metadata) that Illustrator
  opens without crashing. Opens in Illustrator, Inkscape, Affinity, browsers.
- **EPS** — Encapsulated PostScript, re-saveable as `.ai`.
- **PDF** — same content for print pipelines.

All writers preserve transparency (no background drawn). PDF/EPS use the correct
fill rule per engine (nonzero for vtracer, even-odd for potrace).

> **Fixes applied:** (1) earlier builds hand-rolled a minimal PDF that parsed
> correctly but was too bare for Illustrator and crashed it — `render_pdf` now
> uses ReportLab, with the minimal writer kept only as a dependency-free
> fallback; (2) `svgparse` now applies each path's `transform` (vtracer places
> every path with a `translate()`), so AI/EPS exports are positioned correctly
> instead of offset.

## Quality and limits

- Best on **flat art**: logos, icons, line art, stickers, decals, cut files.
- Gradients and softer images work well with `--style photo` (many thin layers).
- It is a **tracer**, so output is an approximation, not a pixel-exact copy — on
  flat-colour art the Potrace reconstruction is ≈**99%** accurate (see tests).
- Fine textures (fur, grain, watercolour) are out of scope.
- Semi-transparent pixels are thresholded, not modelled as alpha shapes.

### Tuning for a closer match

Fidelity is a knob, not a fixed value. To push visual match higher (more nodes,
smoother shapes):

- `--style photo` — `color_precision=8`, `layer_difference=4` (many layers).
- `--detail 2` (or `1`) — vtracer `layer_difference`; **smaller = more colour
  layers = higher match** (and a larger file).
- Raise `path_precision` in `reavectors/vtracer_engine.py` for finer curve
  coordinates if editor rounding is visible.

More match always costs nodes/file size, so pick the point on that curve your
workflow needs.

### Refining for higher detail (the "spend 10 seconds" mode)

Pass `--refine N` (CLI), `refine=N` (API), or tick **Refine** in the web UI and
the backend keeps working for up to N seconds instead of returning instantly. It
runs a closed loop:

```
trace → rasterise the vector → measure how well it matches the source → trace
again with more detail → keep it only if the match improved → repeat until the
time budget is spent
```

Every pass actually tries harder (more colour layers, higher colour precision,
finer coordinates, different corner/speckle/hierarchy settings) and only replaces
the result when the measured **match %** improves, so more time can only help.

```powershell
python -m reavectors photo.png --style photo --refine 10 --format ai
#   refine pass 1:  match 87.06%
#   refine pass 2:  match 87.08%
#   ...
#   refine pass 17: match 87.29%
#   refine   : 17 passes, match 87.29%, 11.2s
```

The reported `match` is the percentage of pixels within tolerance of the source
(measured on a downscaled copy for speed) — the same 0–100% you were comparing.

In the **web UI**, refining streams live progress over **Server-Sent Events**
(`POST /api/refine`): the preview shows a spinner and a running
`Refining… pass N · 3.4s · match 97.3% · vtracer` readout while the backend
works, so you can see it is not returning instantly. If a run converges early
(the settings stop improving), it stops rather than idling; complex images use
the full budget.

## Troubleshooting

**"Vectorize returns instantly / no loading animation."** You are almost
certainly talking to a **server process started before the refine feature
existed** (the old UI/API has no `refine`). Stop it and start a fresh one:

Stop the old server (press **Ctrl+C** in the window it is running in, or close
that window), then start a fresh one:

```powershell
python -m reavectors.server
```

Then check the version in the page header ("server reavectors/0.2") or:

```powershell
curl http://127.0.0.1:8756/api/health
# {"ok": true, "app": "reavectors", "version": "reavectors/0.2",
#  "features": ["refine", "sse", "vtracer"]}
```

If `features` has no `"refine"`, the server is stale. The header pill turns red
and says "outdated — restart it" when it detects this.

### Honest comparison to a hosted AI vectorizer

Services like PerfectVector use a **trained model** that reconstructs curves,
edges and colours. This project uses **classical vectorisation** (vtracer /
Potrace). vtracer closes most of the gap on colour and gradients, but a learned
model can still produce smoother, lower-node-count curves and handle messy
sources better. Matching that exactly would require a GPU and an open
image→SVG model; this machine has no CUDA GPU, so the classical engines are the
practical choice here.

## Project layout

```
reavectors/
├── reavectors/
│   ├── config.py          # env-driven limits (upload, rate, concurrency, API key, Supabase)
│   ├── security.py        # rate limiter, concurrency gate, image validation, headers
│   ├── db.py              # optional Supabase log + keep-alive activity
│   ├── server.py          # stdlib HTTP server (routes, SSE, hardening)
│   ├── vectorize.py       # entry point + Potrace engine + geometry model
│   ├── vtracer_engine.py  # vtracer runner (subprocess-isolated)
│   ├── _vtracer_worker.py # the isolated worker
│   ├── refine.py          # time-budgeted closed-loop refiner (trace->score->keep best)
│   ├── svgparse.py        # SVG path -> geometry, incl. transforms (for AI/EPS export)
│   ├── export.py          # geometry -> PDF/AI + EPS writers
│   └── cli.py             # command line
├── web/                   # drag-and-drop UI (vanilla HTML/CSS/JS)
├── samples/               # make_sample.py + example outputs
├── tests/                 # reconstruction + format + engine + security tests
├── .github/workflows/     # keep-alive cron
├── render.yaml            # Render blueprint
├── .env.example           # template of every env var (no real secrets)
└── LICENSE
```

> Note: the current `vtracer` wheel aborts on **keyword** arguments; the runner
> uses positional arguments and isolates vtracer in a subprocess, so a crash
> falls back to Potrace instead of taking down the process.

## Tests

```powershell
python tests/test_reavectors.py
```

Covers: empty transparency, SVG/PDF/EPS headers, **PDF xref object offsets**,
the **SVG path parser**, vtracer engine selection, and a **reconstruction
agreement** check (≈0.99).

## Security & limits

The server is hardened for public exposure. Everything is tunable via env vars
(see `reavectors/config.py`); defaults:

| Env var | Default | Purpose |
|---|---|---|
| `REAVECTORS_MAX_UPLOAD_MB` | `12` | max request body (checked before reading) |
| `REAVECTORS_MAX_DIM` | `8000` | max image edge (px) |
| `REAVECTORS_MAX_PIXELS` | `40000000` | decompression-bomb guard |
| `REAVECTORS_RATE` | `60` | requests / minute / IP |
| `REAVECTORS_REFINE_RATE` | `12` | refine requests / minute / IP |
| `REAVECTORS_MAX_CONCURRENCY` | `4` | simultaneous heavy jobs (rest queue / 503) |
| `REAVECTORS_REFINE_MAX_SECONDS` | `12` | server-side cap on refine time |
| `REAVECTORS_API_KEY` | *(unset)* | if set, require `X-API-Key` on `/api/*` |

What's enforced:

- **Input validation** — every upload is opened with Pillow, restricted to a
  raster-format allow-list, and rejected on size / dimension / pixel limits
  (`415` / `413`). Non-images never reach the tracer.
- **Rate limiting** — per-IP sliding window (`429` + `Retry-After`).
- **Concurrency cap** — a global gate limits simultaneous traces so a burst
  can't exhaust the CPU; excess requests wait briefly or get `503`.
- **Security headers** — strict CSP, `nosniff`, `X-Frame-Options: DENY`,
  no-referrer, Permissions-Policy, COOP/CORP.
- **API key (optional)** — set `REAVECTORS_API_KEY` to lock the API; the bundled
  web UI is served with the key injected, so the page keeps working for people
  you share the link with. It is an *unlisted-link* control, not identity auth.
- **Secrets** — the Render API key is never stored in the repo or code.

Run locally with a locked API and custom limits:

```powershell
$env:REAVECTORS_API_KEY="my-secret"; $env:REAVECTORS_RATE="120"
python -m reavectors.server
```

## Scaling to thousands of requests/day

5,000–10,000 requests/day is ~0.1 req/s average — small. What matters is *CPU
per request*, because tracing is the cost:

- A quick vectorize is ~0.2–1 s; a full `refine` is up to `REFINE_MAX_SECONDS`.
- The **concurrency gate** keeps the box responsive under bursts; the **result
  cache** (keyed by image hash + params) makes repeat/duplicate work free.
- Recommended: cap refine (default 12 s), keep the **cache** on, and give the
  service headroom with a paid instance (Starter = 0.5 CPU/512 MB, Standard =
  1 CPU/2 GB). If you expect many concurrent *refines*, prefer **Standard** and
  keep `MAX_CONCURRENCY` ≈ CPU count.
- The web UI and API are separate concerns: public traffic stays rate-limited;
  heavy programmatic jobs should use an API key and a bounded refine budget.

## Backend database (Supabase) & always-on

The service can log activity to **Supabase** (Postgres via the PostgREST HTTP
API). It is optional and **best-effort** — if the DB is unreachable, conversions
still work.

- Every vectorize / refine / export writes a small row to `conversions`
  (engine, style, counts, match %, seconds — **no image data, no IPs**).
- `GET /api/stats` returns `{total, today, engines}` (cached).
- `GET /api/health` reports `"db": "on" | "off"`.

Setup used here (project ref `qpfvblqtwhmndckghirs`):

```sql
create table public.conversions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  kind text not null default 'vectorize',
  engine text, style text, colors int, figures int, subpaths int,
  match_pct numeric, seconds numeric, fmt text
);
alter table public.conversions enable row level security;  -- service-role only
```

The server connects with the **service-role** key held in the host environment.
RLS is on with **no policies**, so the public anon key cannot read the table, and
the service key never leaves the server.

### One cron keeps the whole stack awake

Free tiers sleep when idle — Render after ~15 min, Supabase after **7 days**.
`.github/workflows/keepalive.yml` pings the public `/api/health` every 10 min:

```
GitHub Actions (every 10 min)  ->  Render /api/health  ->  Supabase (hourly touch)
```

So a single cron keeps **Render and Supabase** online with **no manual requests**
and **no secrets in GitHub** (the endpoint is public). GitHub pauses scheduled
workflows after 60 days of repo inactivity; any commit re-enables it.

## Where secrets live (and how to rotate them)

There are exactly **two** places a secret ever lives, and **neither is git**:

| Place | Holds | Used by |
|---|---|---|
| **Local `.env`** (git-ignored) | `RENDER_API_KEY`, `SUPABASE_ACCESS_TOKEN`, and a copy of the runtime keys | you + the helper scripts (and me, when you ask me to do deploy work) |
| **Render → Environment** (encrypted) | the runtime keys: `SUPABASE_SERVICE_KEY`, `SUPABASE_URL`, limits | the running service |

`.env.example` (committed) is the template; `.env` never leaves your machine.

**Where to paste your NEW Render API key after rotating it:** the line
`RENDER_API_KEY=` in `C:\Users\Hp\Documents\Default Project\reavectors\.env`.
That's the only place I look. I read it from there at use time and never print or
commit it. If you'd rather not keep it on disk, just paste it to me when needed.

### Rotate in three steps

```powershell
cd "C:\Users\Hp\Documents\Default Project\reavectors"

# 1) paste the new key(s) into .env, then push runtime keys to Render:
.\scripts\render-set-env.ps1

# 2) redeploy so the new values take effect:
.\scripts\render-deploy.ps1
```

- **Render API key** → regenerate in Render → Account Settings → API Keys → paste into `.env` (`RENDER_API_KEY`).
- **Supabase service_role key** → Project Settings → API → regenerate → paste into `.env` (`SUPABASE_SERVICE_KEY`) → `render-set-env.ps1` → `render-deploy.ps1`.
- **Supabase account token (`sbp_…`)** → Account → Access Tokens → regenerate → `.env` (`SUPABASE_ACCESS_TOKEN`).
- **GitHub token** → prefer `gh auth` / Windows Credential Manager; only add `GITHUB_TOKEN` to `.env` if a script needs it.

## Portable — clone anywhere, run anywhere

The repo is the single source of truth; nothing essential lives only on your PC.
On a new machine:

```powershell
git clone https://github.com/rizbiehelp-sys/reavectors
cd reavectors
pip install -r requirements.txt
copy .env.example .env     # paste your keys
python -m reavectors.server
```

…or with Docker (no Python on the host needed):

```powershell
docker build -t reavectors .
docker run -p 8756:8756 --env-file .env reavectors
```

Local disk stays small: caches (`__pycache__`, `samples/out`, `.pytest_cache`) are
git-ignored and regenerable, and `PYTHONDONTWRITEBYTECODE=1` is set in the image.
Nothing about the deployment depends on this PC — Render builds from GitHub, and
the keep-alive runs on GitHub. If the PC dies you lose only the local `.env`;
everything else (code, config template, CI) is on GitHub, and the secrets are on
Render.

## Deploy on Render

This repo is Render-ready (`render.yaml`, binds `0.0.0.0:$PORT`, health check at
`/api/health`).

**Live service:** https://reavectors.onrender.com

- **Type:** Web Service · **Runtime:** Python 3.12 · **Region:** Oregon
- **Build:** `pip install -r requirements.txt`
- **Start:** `python -m reavectors.server`
- **Health check:** `/api/health`

### Staying online (free)

Render's **free** instances sleep after ~15 minutes idle and cold-start on the
next hit. This repo includes `.github/workflows/keepalive.yml`, which pings
`/api/health` every 10 minutes to keep it warm — that fits inside Render's free
monthly allowance (~720 h of 750 h). GitHub pauses *scheduled* workflows after
60 days of repo inactivity; any commit or manual run re-enables it.

### Truly always-on without cold starts

Swap the free plan for a paid instance (e.g. **Starter**, ~$7/mo, covered by the
account credits) — no sleeping, no cold starts. One API call:

```powershell
$key = "<your Render API key>"
$sid = "<service id>"
Invoke-RestMethod -Method PATCH -Uri "https://api.render.com/v1/services/$sid" `
  -Headers @{ Authorization = "Bearer $key"; "Content-Type" = "application/json" } `
  -Body '{"serviceDetails":{"plan":"starter"}}'
```

### Notes

- The service is **public and unauthenticated** — anyone with the URL can use
  CPU. Add auth or a rate limit before promoting it widely.
- Uploads are processed in memory and never persisted; the refiner runs the
  native tracer (vtracer) in an isolated subprocess.

## License / intent

Original code for lawful use: converting images **you have the rights to**.
Rights and licensing for any input artwork are the user's responsibility.
