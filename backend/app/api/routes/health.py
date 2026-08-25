from __future__ import annotations
from fastapi import APIRouter
from backend.app.config import get_settings
from backend.app.db.session import check_db
from backend.app.schemas.health import HealthResponse, RootResponse

router = APIRouter(tags=["health"])
settings = get_settings()

@router.get("/", response_model=RootResponse)
def root():
    return RootResponse(name=settings.app_name, version=settings.app_version, env=settings.app_env, docs="/docs")

@router.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version=settings.app_version, env=settings.app_env, db=check_db(), model_provider=settings.model_provider, model_id=settings.model_id)
