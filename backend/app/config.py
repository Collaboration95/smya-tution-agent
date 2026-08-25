from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="SMYA Co-Tutor API")
    app_env: str = Field(default="local")  # local | test | production
    app_version: str = Field(default="0.1.0-s1")
    # Postgres is primary; SQLite is the zero-dependency fallback for S1 local/CI.
    database_url: str = Field(
        default="sqlite:///./smya.db",
        description="SQLAlchemy URL. Use postgresql+psycopg2://user:pass@host/db for Postgres.",
    )
    # Model provider boundary — only 'fake' is wired in S1.
    model_provider: str = Field(default="fake")
    model_id: str = Field(default="fake-diagnostic-v1")
    # CORS
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
