"""Assemble rendered PNG frames into an MP4 with FFmpeg.

  python blender/scripts/render_video.py --frames-dir out/frames --fps 24 --out out/ad.mp4

Also validates the MP4 exists and reports its size. Run from a normal Python
(FFmpeg must be on PATH) or from Blender's Python.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys


def encode(frames_dir: str, fps: int, out: str) -> dict:
    frames = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    if not frames:
        raise SystemExit(f"no frames in {frames_dir}")
    pattern = os.path.join(frames_dir, "frame_%04d.png")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found on PATH")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmd = [ffmpeg, "-y", "-framerate", str(fps), "-i", pattern,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("ffmpeg failed: " + (r.stderr or "")[-400:])
    return {"ok": True, "out": out, "frames": len(frames), "fps": fps,
            "bytes": os.path.getsize(out) if os.path.exists(out) else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    print(json.dumps(encode(args.frames_dir, args.fps, args.out)))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise