# ReaVector Blender pipeline (Phase 3)

Real parametric product geometry + your **actual label artwork** → validated **GLB**.
This replaces "rotating pictures" with true 3D. The browser viewer already renders
the GLB (`/model3d.html`, `/product3d.html`).

## Scripts

| File | Purpose |
|---|---|
| `scripts/common.py` | lathe/revolve geometry, materials, cylindrical UVs, GLB export |
| `scripts/build_product.py` | build `bottle` / `jar` / `can` / `tube` / `box`, export GLB |
| `scripts/apply_label.py` | map the real label image onto the body |
| `scripts/export_glb.py` | export + validate the GLB header |

## Run headless

Install Blender 4.x (or use a GPU/worker image that has it), then:

```bash
blender --background --python blender/scripts/build_product.py -- \
  --type bottle --out out/bottle.glb --label label.png --color "#B3122E" --material plastic
```

Other shapes:

```bash
blender --background --python blender/scripts/build_product.py -- --type jar  --out out/jar.glb  --color "#2E7D32"
blender --background --python blender/scripts/build_product.py -- --type can  --out out/can.glb  --color "#0D47A1"
blender --background --python blender/scripts/build_product.py -- --type box  --out out/box.glb  --params '{"width":0.12,"depth":0.06,"height":0.2}'
```

`build_product.py` prints JSON: `{"ok": true, "type": "...", "out": "..."}`.
`export_glb.py` also reports `valid_glb` (checks the `glTF` magic).

## Why Blender

- Accurate **shape + real label texture** (never AI-invented text).
- Deterministic, repeatable geometry for product ads.
- AI (TRELLIS.2) is optional and needs ≥24 GB VRAM — not a T4 default.

## Where it runs

Not on the Render web request. Run it:
- locally with Blender installed, or
- in a manual GPU/CPU worker session (Kaggle/Colab) that has Blender, then upload the
  GLB through the ReaVector bridge (`POST /api/ai/bridge/jobs/<id>/result`).

## Fallback (no Blender)

The **Product 3D** page already builds parametric packaging in-browser with Three.js
`LatheGeometry` and exports a real **GLB** via `GLTFExporter` — so users still get a
usable model when Blender isn't available.