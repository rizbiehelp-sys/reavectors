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
│   ├── vectorize.py       # entry point + Potrace engine + geometry model
│   ├── vtracer_engine.py  # vtracer runner (subprocess-isolated)
│   ├── _vtracer_worker.py # the isolated worker
│   ├── refine.py          # time-budgeted closed-loop refiner (trace->score->keep best)
│   ├── svgparse.py        # SVG path -> geometry, incl. transforms (for AI/EPS export)
│   ├── export.py          # geometry -> PDF/AI + EPS writers
│   ├── cli.py             # command line
│   └── server.py          # stdlib HTTP server + JSON/binary API
├── web/                   # drag-and-drop UI (vanilla HTML/CSS/JS)
├── samples/               # make_sample.py + example outputs
└── tests/                 # reconstruction + format + engine tests
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
