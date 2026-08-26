# SMYA Backend — S1/S3 bounded agent workflows

FastAPI + Pydantic + SQLAlchemy, Postgres (SQLite fallback), fake ModelClient.

## Local dev (no secrets)

```sh
# 1) Python env
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
# or: pip install -e backend[dev]

# 2) DB — Postgres via docker (recommended) or SQLite fallback
docker compose up -d db
# .env already defaults to sqlite:///./smya.db for zero-dependency runs
# To use Postgres: DATABASE_URL=postgresql+psycopg2://smya:smya@localhost:5432/smya

# 3) Run API
uvicorn backend.app.main:app --reload --port 8000
# Health
curl http://localhost:8000/health
curl http://localhost:8000/

# 4) Seed check (no secrets, no network)
python3 backend/scripts/seed.py

# 5) Run one queued diagnostic job (or omit --once to poll continuously)
python3 backend/scripts/worker.py --once

# Parent-report drafts use the same durable worker contract and remain for tutor review.
python3 backend/scripts/worker.py --once --job-type parent_report

# 6) Tests
pytest backend/tests -v
pytest -q
# Fixture contract (repo root)
python3 scripts/validate_s0_fixtures.py
```

## Migrations (Alembic)

```sh
alembic -c backend/alembic.ini revision --autogenerate -m "describe"
alembic -c backend/alembic.ini upgrade head
# Ephemeral test DBs may use Base.metadata.create_all instead.
```

## Model provider

`MODEL_PROVIDER=fake` (default) uses `FakeModelClient` — deterministic, no network.
Groq/Bedrock adapters land in S4 behind the same `ModelClient` interface.
