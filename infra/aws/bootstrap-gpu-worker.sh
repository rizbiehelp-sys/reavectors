#!/usr/bin/env bash
# ReaVector GPU worker bootstrap
# ------------------------------------------------------------------------------
# RUN THIS MANUALLY, ON THE GPU INSTANCE ONLY (g4dn.xlarge, Ubuntu + NVIDIA driver).
# It is NOT run by the app and does NOT create any AWS resources.
#
# Prereqs (you create these manually): the instance exists, has an IAM instance
# profile with infra/aws/gpu-worker-iam-policy.json, and a persistent EBS volume
# mounted at $MODELS_DIR.
#
# No secret is stored here. Credentials come from the EC2 instance profile.
set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/mnt/models}"          # persistent EBS mount (weights + hf cache)
APP_DIR="${APP_DIR:-/opt/reavectors}"
QUEUE_URL="${QUEUE_URL:?set QUEUE_URL in /etc/reavectors/worker.env}"
ASSETS_BUCKET="${ASSETS_BUCKET:?set ASSETS_BUCKET in /etc/reavectors/worker.env}"

echo "== 1/6 system packages =="
sudo apt-get update
sudo apt-get install -y python3 python3-venv git awscli nvtop

echo "== 2/6 persistent model cache on EBS ($MODELS_DIR) =="
sudo mkdir -p "$MODELS_DIR"
export HF_HOME="$MODELS_DIR/hf"
export TORCH_HOME="$MODELS_DIR/torch"
echo "export HF_HOME=$HF_HOME" | sudo tee /etc/profile.d/reavectors-models.sh

echo "== 3/6 app checkout =="
sudo mkdir -p "$APP_DIR" && sudo chown "$USER":"$USER" "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "${REPO_URL:?set REPO_URL}" "$APP_DIR"
fi
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Worker deps (torch/diffusers/comfy) are installed per-model adapter on purpose —
# do NOT load models on the control plane, and keep this instance's set minimal.

echo "== 4/6 worker env file (no secrets; profile-based creds) =="
sudo mkdir -p /etc/reavectors
sudo tee /etc/reavectors/worker.env >/dev/null <<EOF
QUEUE_URL=$QUEUE_URL
ASSETS_BUCKET=$ASSETS_BUCKET
MODELS_DIR=$MODELS_DIR
AI_GPU_PROVIDER=ec2
HF_HOME=$HF_HOME
EOF

echo "== 5/6 systemd unit =="
sudo cp infra/aws/worker.service /etc/systemd/system/reavectors-worker.service
sudo systemctl daemon-reload

echo "== 6/6 done =="
echo "Start with:  sudo systemctl enable --now reavectors-worker.service"
echo "Admin via SSM Session Manager (no public SSH)."
