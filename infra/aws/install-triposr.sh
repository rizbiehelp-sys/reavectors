#!/usr/bin/env bash
# Install the TripoSR image-to-3D model on the GPU worker.
# -----------------------------------------------------------------------------
# RUN MANUALLY, ON THE g4dn.xlarge ONLY. It does not create any AWS resource and
# does not run on the control plane. Model weights stay on the persistent EBS
# (HF_HOME), so a stop/start does not re-download them.
set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/mnt/models}"
TRIPOSR_DIR="${TRIPOSR_DIR:-/opt/TripoSR}"
export HF_HOME="${HF_HOME:-$MODELS_DIR/hf}"

echo "== 1/4 CUDA / nvidia check =="
nvidia-smi || { echo "No NVIDIA driver — is this really the GPU instance?"; exit 1; }

echo "== 2/4 worker python deps (torch cu121 + TripoSR deps) =="
pip install --upgrade pip setuptools
pip install -r "$(dirname "$0")/requirements-worker.txt"

echo "== 3/4 clone TripoSR (MIT) =="
if [ ! -d "$TRIPOSR_DIR/.git" ]; then
  git clone https://github.com/VAST-AI-Research/TripoSR "$TRIPOSR_DIR"
fi
pip install -r "$TRIPOSR_DIR/requirements.txt" || true   # some are already satisfied

echo "== 4/4 pre-download the weights into the EBS cache =="
python - <<'PY'
import os
from huggingface_hub import hf_hub_download
for f in ("config.yaml", "model.ckpt"):
    p = hf_hub_download(repo_id="stabilityai/TripoSR", filename=f)
    print("cached:", p)
PY

cat <<EOF

Done. Verify a single inference (this proves the T4 works before enabling public use):
  cd $TRIPOSR_DIR
  PYTHONPATH=$TRIPOSR_DIR python run.py examples/chair.png --output-dir /tmp/triposr_out
  ls -l /tmp/triposr_out            # expect a .obj/.glb mesh

Then point the worker at it:
  export TRIPOSR_REPO=$TRIPOSR_DIR
  export MODELS_DIR=$MODELS_DIR
EOF
