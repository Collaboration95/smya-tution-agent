#!/usr/bin/env python3
"""Run one bounded diagnostic or parent-report worker against queued jobs."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.agents.worker import run_next_job
from backend.app.db.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", default="worker-diagnostic-1")
    parser.add_argument("--job-type", choices=("diagnostic", "parent_report"), default="diagnostic")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    while True:
        with SessionLocal() as db:
            result = run_next_job(db, args.worker_id, job_type=args.job_type)
        if result:
            print(result)
        if args.once:
            return 0
        time.sleep(max(args.poll_seconds, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
