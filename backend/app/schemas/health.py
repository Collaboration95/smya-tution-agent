from __future__ import annotations
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    version: str
    env: str
    db: str
    model_provider: str
    model_id: str

class RootResponse(BaseModel):
    name: str
    version: str
    env: str
    docs: str
