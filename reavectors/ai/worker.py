"""
GPU worker entry point (systemd: ``python -m reavectors.ai.worker``).

SKELETON. This file is intentionally inert until the real inference adapters and
SQS wiring exist. It will **not** load models on the control plane and does not
run on the t3.micro. It requires an explicit environment (queue URL + a GPU).

Safety:
* Exits immediately if no queue is configured (so it can never accidentally run
  on the controller).
* Never touches AWS unless ``AI_QUEUE_BACKEND=sqs`` and credentials come from the
  instance profile (no keys in code).
"""

from __future__ import annotations

import os
import sys
import time

from .. import config


def main() -> int:
    backend = config.AI_QUEUE_BACKEND
    queue_url = os.environ.get("QUEUE_URL", "")

    if backend != "sqs" or not queue_url:
        print("[worker] not configured (set AI_QUEUE_BACKEND=sqs and QUEUE_URL). "
              "This skeleton does nothing here.", file=sys.stderr)
        return 2

    print(f"[worker] starting; queue_backend={backend} queue={queue_url[:24]}… "
          f"models_dir={os.environ.get('MODELS_DIR', '(unset)')}", file=sys.stderr)

    # TODO(phase 4+): poll SQS -> load model via a model manager -> run adapter ->
    # upload result to private S3 -> publish heartbeat. Until implemented, idle.
    while True:
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            break
    print("[worker] stopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
