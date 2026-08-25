# SMYA — Show Me Your Agents (S1 branch)

Epic S1 vertical slice: durable learning event → bounded diagnostic job → evidence-backed MasteryProposal → tutor review.

See `docs/decisions/ADR-0002-s1-bootstrap-and-vertical-slice.md` for stack + boundaries.

## Quick start (no secrets)

```sh
# fixtures
python3 scripts/validate_s0_fixtures.py

# backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
# http://localhost:8000/health  http://localhost:8000/docs

# Postgres optional (otherwise SQLite ./smya.db is used)
docker compose up -d db
DATABASE_URL=postgresql+psycopg2://smya:smya@localhost:5432/smya uvicorn backend.app.main:app --reload

# synthetic seed check
python3 backend/scripts/seed.py

# bounded worker (after creating a diagnostic job)
python3 backend/scripts/worker.py --once

# tests
pytest backend/tests -v
pytest -q  # includes S0 fixture tests
python3 -m unittest discover -s tests -v

# frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
npm run build

# optional frontend-to-API override (defaults to http://localhost:8000)
# NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

## S1 issues

- S1-01 Bootstrap FastAPI/Next.js/Postgres contract (this commit)
- S1-02 Tenant-scoped learning records + deterministic mastery
- S1-03 RBAC + typed tool trust boundaries
- S1-04 AgentJob/AgentRun + fake ModelClient lifecycle
- S1-05 Diagnostic worker + MasteryProposal
- S1-06 Tutor trace & proposal review screen
