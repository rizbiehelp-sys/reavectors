# IMAGE STUDIO PIPELINE AUDIT (Phase 0 for the unified image engine)

## Current state (from the live page + code)

`/image.html` today:
- Provider select: **Cloudflare** (added) and **Kaggle GPU**.
- Model select: filled from the AI **registry** (Kaggle models: sdxl, z-image, ...).
  -> When Cloudflare is chosen, the model list still shows **Kaggle model ids**, not
  the Cloudflare model. This is the reported bug.
- A "Product scene — keep my label" checkbox and a single optional photo.
- A hardcoded juice prompt placeholder (removed in this rebuild).
- Cloudflare path calls `POST /api/ai/cf/image` with `{prompt}` only.

## Root causes found

1. **Model list is registry-driven** (`image.js: fill()` filters `MODELS` by task),
   so it never reflects the provider. With Cloudflare selected the user still sees
   `sdxl-base-1.0`, etc.
2. **Cloudflare `flux-1-schnell` ignores the uploaded photo** (text-to-image only).
   The reference image was never part of the request, so the output was a generated
   juice, not the user's milk bottle.
3. **Background removal** used border-colour thresholding: fine for plain backdrops,
   weak for real photos; no alpha matte, no BiRefNet.
4. **No reference understanding** and no "what ReaVector understood" panel.
5. Fragmented UX: separate checkbox, no main/result canvas, no transparent export.

## Decision

Rebuild image generation around **one pipeline**:

- **Preserve product (default ON)** — cut out the real product, generate only the
  background with Cloudflare, composite the **original pixels** (label intact).
- **Transparent PNG** — return the RGBA cutout.
- **No main image** — text-to-image with Cloudflare.
- Provider is **Cloudflare only** for image (per request); the model select lists
  **Cloudflare models** (`flux-1-schnell` text→image, `flux-2-klein-4b` edit/multipart).
- One page, one upload workspace (main + multiple references), one prompt, one
  Generate, one result canvas, before/after, downloads.

## Endpoints (new, unified)

- `POST /api/image/generate` (multipart: `image`, `references[]`, `prompt`,
  `preserve`, `transparent`, `model`) -> `{artifact,url,mode,background,understood,preserve}`
- `POST /api/image/analyze` (multipart image) -> structured "understood" JSON.

Existing `/api/ai/cf/image` and `/api/ai/composite` remain as thin aliases.

## Honest limits

- BiRefNet (5.5 GB) cannot run on Render; CPU uses an improved border/alpha cutout.
  A Kaggle worker notebook for BiRefNet-matting is the next GPU step.
- Qwen-Image-Edit-2509 (20B) is GPU-only and not a T4 default.
- Cloudflare `flux-2-klein-4b` requires multipart image input (edit), so it is not
  used for pure text-to-image.
- A single photo cannot reveal unseen sides; preserve mode keeps the photographed
  view exactly and must not claim new angles.