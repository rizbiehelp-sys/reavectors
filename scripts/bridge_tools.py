#!/usr/bin/env python3
"""
Bridge housekeeping / output collector.

    python scripts/bridge_tools.py --clear                 # delete old jobs + artifacts
    python scripts/bridge_tools.py --clear --keep-artifacts # delete only job_*.json
    python scripts/bridge_tools.py --collect "C:\\Users\\Hp\\Downloads\\ReaVector"
    python scripts/bridge_tools.py --list

Uses SUPABASE_URL + SUPABASE_SERVICE_KEY from the environment (.env is loaded if present).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import requests

BUCKET = os.environ.get("AI_BRIDGE_BUCKET", "ai-bridge")


def load_env():
    for path in (".env", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
        if os.path.isfile(path):
            for line in io.open(path, encoding="utf-8"):
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))
            break


def cfg():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        sys.exit(2)
    return url, key


def names(url, key):
    r = requests.post(f"{url}/storage/v1/object/list/{BUCKET}",
                      json={"prefix": "", "limit": 1000, "offset": 0},
                      headers={"Authorization": f"Bearer {key}", "apikey": key}, timeout=30)
    r.raise_for_status()
    return [i["name"] for i in r.json() if i.get("name")]


def delete(url, key, paths):
    if not paths:
        return 0
    r = requests.delete(f"{url}/storage/v1/object/{BUCKET}",
                        json={"prefixes": paths},
                        headers={"Authorization": f"Bearer {key}", "apikey": key}, timeout=60)
    if r.status_code >= 300:
        print("delete failed", r.status_code, r.text[:200], file=sys.stderr)
        return 0
    return len(paths)


def download(url, key, name, dest):
    r = requests.get(f"{url}/storage/v1/object/{BUCKET}/{name}",
                     headers={"Authorization": f"Bearer {key}", "apikey": key}, timeout=120)
    if r.status_code >= 300:
        return None
    path = os.path.join(dest, name)
    io.open(path, "wb").write(r.content)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--keep-artifacts", action="store_true")
    ap.add_argument("--collect", default="")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    load_env()
    url, key = cfg()
    all_names = names(url, key)
    print("objects:", len(all_names))

    if args.list:
        for n in all_names:
            print("  ", n)

    if args.clear:
        jobs = [n for n in all_names if n.startswith("job_")]
        arts = [] if args.keep_artifacts else [n for n in all_names if n.startswith("art_")]
        print("deleting jobs:", len(jobs), "artifacts:", len(arts))
        print("removed:", delete(url, key, jobs + arts))

    if args.collect:
        os.makedirs(args.collect, exist_ok=True)
        arts = [n for n in names(url, key) if n.startswith("art_")]
        manifest = []
        for n in arts:
            p = download(url, key, n, args.collect)
            if p:
                manifest.append({"file": n, "bytes": os.path.getsize(p)})
                print("saved", p)
        io.open(os.path.join(args.collect, "manifest.json"), "w", encoding="utf-8").write(
            json.dumps({"collected_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                        "files": manifest}, indent=2))
        print("collected", len(manifest), "->", args.collect)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())