# Product Photo → 3D

Real product photograph → realistic, brand-accurate 3D asset. **Not** PNG extrusion.
The dedicated tool lives at `/product3d.html` ("Product 3D" in the nav) and is kept
separate from the 2D Vectorizer and the PNG/SVG **3D Studio** (`/studio3d.html`).

## Workflow (implemented)

1. **Capture** — phone/camera photo (JPG / PNG / WebP; RAW exported to JPG).
2. **Upload** — original photograph kept for the job.
3. **Cutout** — transparent isolation from a measured background estimate
   (`ai/product3d.py:make_cutout`).
4. **Silhouette + geometry** — per-row width profile → packaging class →
   parametric lathe profile (`build_lathe_profile`, `classify_package`).
5. **Label** — the **original** artwork is extracted and perspective-corrected
   (`rectify_label`) or a flat SVG/PNG is accepted verbatim.
6. **Reconstruct** — separate body / base / neck-cap / label components
   (Three.js `LatheGeometry` + `CylinderGeometry`, browser-side).
7. **Map label** — rectified artwork wrapped on the body band (arc + rotation
   adjustable), colours/text preserved.
8. **Materials + lighting** — body material (plastic / glass / metal) with a studio
   environment for reflections; metal cap.
9. **Viewer** — rotate / zoom / pan / wireframe.
10. **Export GLB** — original label texture embedded.

## Exact branding (never generated)

Brand names, logos, nutrition panels, ingredients, volume labels and package
typography are **never** produced by a model. The pipeline uses only the source
photograph or a supplied label asset, with `source: "rectified_from_photo"` or
`"supplied_asset"` recorded in the response. If the photo can't support accurate
detail, the quality report says so instead of faking it.

## Two modes

| Mode | Input | Output |
|---|---|---|
| **Single photo** (`mode=single`) | one photo | attractive approximation; visible front label preserved; hidden geometry **inferred** |
| **High-fidelity** (`mode=high_fidelity`) | front + back + side, optional flat label SVG/PNG | more evidence, complete label wrapping, fewer inferred areas |

The UI shows a **capture guide** (straight-on, even light, plain background) when
high-fidelity is selected. Back/side views feed the AI pass on the GPU worker; the
CPU parametric pass always uses the primary (front) photo.

## Quality checks

`quality_report()` returns symmetry, object coverage, silhouette consistency, a
confidence band (low/medium/high) and explicit warnings. The studio displays them
and every result states that the back/hidden side is **inferred**. Before export the
UI surfaces: label source, material hint (to confirm — transparency/reflections),
and confidence. Plural/backside geometry is always labelled approximate.

## Refine budget (it should NOT be instant)

Like the 2D vectorizer's refine, the reconstruction runs a **real, time-boxed
refinement** and only returns when the budget is spent:

- `?refine=<seconds>` (or the **Refine effort** slider in the studio), clamped to
  `PRODUCT3D_REFINE_MIN`..`PRODUCT3D_REFINE_MAX` (10-120 s, default 30).
- `?stream=1` (what the studio uses) streams **Server-Sent Events**: a
  `progress` event per stage/iteration (`stage`, `pct`, `elapsed`, `budget`),
  then a final `done` with the spec. Without `stream`, the same pipeline returns
  JSON (used by tests/API).
- The budget is spent on genuine work, not a sleep:
  - **cutout**: iterative guided-filter alpha matting (hundreds of passes at 30 s)
    snapping the mask to real image edges so transparent edges/reflections survive,
  - **profile**: iterative smoothing/fit (128 points at high budget),
  - **label**: structure-based band detection + iterative unsharp enhancement.

The `work` block in the response reports `used_s`, `cutout_iterations`,
`cutout_edge_score`, `profile_points` and `profile_fit_rmse`. `budget=0` runs a
fast pass (used by the unit tests).

## Environments

- **Control plane (Render)** — CPU: cutout, silhouette analysis, label rectification,
  parametric profile, quality report. No GPU needed.
- **Python API** — `POST /api/ai/product3d` (multipart: `image` required,
  `label`/`back`/`side` optional, `mode`, `material`) → the spec JSON.
- **Kaggle** — personal, non-commercial benchmarking of TripoSR / SF3D on the dual
  T4 (see `bench/`). **Not** connected to public requests.
- **AWS g4dn.xlarge** — authorised public production GPU worker for AI surface
  reconstruction; stopped when idle, started only after validated jobs, with cost
  guards. TripoSR (MIT) is the default; SF3D is opt-in (Community License).

## Honest limits

- One photograph cannot reveal the true back side — geometry and backside texture
  there are **inferred**.
- The parametric mesh is measured from the silhouette; a single view cannot recover
  hidden concavities. AI reconstruction (GPU) refines unknown surfaces but **never**
  the branding.
- Transparent regions and reflections need a transparent-safe cutout and a manual
  material choice — the auto hint is exactly that, a hint.
