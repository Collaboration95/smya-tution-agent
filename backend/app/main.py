from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import get_settings
from backend.app.api.routes.health import router as health_router

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version, description="SMYA Co-Tutor API — Epic S1 vertical slice")

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(health_router)
from backend.app.api.routes.students import router as students_router  # noqa: E402

app.include_router(students_router)

# Later S1 routers will be included here:
# app.include_router(diagnostic_router, prefix="/api")
# app.include_router(job_router, prefix="/api")
