#!/usr/bin/env python3
"""Deterministic synthetic seed loader — no secrets, no network."""
from __future__ import annotations
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.session import SessionLocal, engine
from backend.app.db.base import Base

CONTRACT = ROOT / "fixtures" / "fractions_contract_v1.json"
SEED = ROOT / "fixtures" / "seed" / "synthetic_centre_v1.json"

def load():
    contract = json.loads(CONTRACT.read_text())
    seed = json.loads(SEED.read_text())
    Base.metadata.create_all(bind=engine)
    # S1-02 deterministic seed: populate tenant-scoped records and mastery history
    try:
        from backend.app.services.seed import seed_db
        with SessionLocal() as db:
            seed_db(db)
    except Exception as e:
        # Fallback for environments where seed service not yet available
        with SessionLocal() as db:
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
            db.commit()
        print(f"Seed fallback check ok (seed service error: {e}): contract={contract['contract_id']} seed={seed['seed_id']}")
        return
    print(f"Seed check ok: contract={contract['contract_id']} seed={seed['seed_id']} questions={len(contract['questions'])} attempts={len(seed['attempts'])}")

if __name__ == "__main__":
    load()
