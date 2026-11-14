# Kaggle GPU runner (personal / owner use)

All GPU inference runs here. Backend stays on **Render + Cloudflare**; AWS is just an
always-on VPS. Kaggle's terms are **personal, non-commercial** — **do not** point
public ReaVector customer requests at a Kaggle session. This is for you (the owner)
generating 3D assets. Each run is manual.

## 1. Create the notebook
- New Notebook → Settings → Accelerator **GPU T4 ×2**.
- Confirm: `!nvidia-smi` shows two Tesla T4.

## 2. Get the code + an image
```bash
!git clone https://github.com/rizbiehelp-sys/reavectors.git
%cd reavectors
!pip -q install numpy pillow trimesh rembg onnxruntime
```
Upload a photo (or use a Kaggle dataset) and note its path, e.g.
`/kaggle/input/my-products/bottle.png`.

## 3. Install the model you want
```bash
# TripoSR (MIT, ~6 GB)
!git clone https://github.com/VAST-AI-Research/TripoSR /opt/TripoSR
!pip -q install -r /opt/TripoSR/requirements.txt
export PYTHONPATH=/opt/TripoSR:$PYTHONPATH
```
(`sf3d`: clone `Stability-AI/stable-fast-3d`; `hunyuan3d`: clone
`Tencent-Hunyuan/Hunyuan3D-2.1` — the last needs ~24 GB, so it won't fit a T4.)

## 4. Generate the GLB
```bash
!python scripts/ai3d_run.py --image /kaggle/input/my-products/bottle.png \
    --model triposr --out /kaggle/working/bottle.glb
```
It prints JSON (`model`, `out`, `bytes`, `seconds`). `bottle.glb` appears in the
notebook's **Output** panel — download it.

## 5. Open it in your studio
Go to https://reavectors.onrender.com/product3d.html → **Open a .glb (from Kaggle)**
→ pick the downloaded file. Rotate / zoom / export. The label/branding in a TripoSR
result is *generated* — for exact branding use the parametric tool or your supplied
label asset.

## Two GPUs at once
Run independent jobs on each T4 in separate cells:
```bash
!CUDA_VISIBLE_DEVICES=0 python scripts/ai3d_run.py --image a.png --model triposr --out out/a.glb
!CUDA_VISIBLE_DEVICES=1 python scripts/ai3d_run.py --image b.png --model sf3d    --out out/b.glb
```

## Benchmarking (optional)
`python bench/kaggle_benchmark.py --image a.png --models triposr,sf3d` writes a
report with inference time, **peak VRAM**, licence and quality notes.

## Note on automation
There is **no** Kaggle→public bridge in this repo by design (ToS). If you ever want
Kaggle to serve public jobs you need Kaggle's written authorisation; until then,
generate manually here and open the GLB in the studio.