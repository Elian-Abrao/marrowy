from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MARROWY_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite+pysqlite:///./marrowy.db"
    test_database_url: str = "sqlite+pysqlite:///:memory:"
    codex_bridge_url: str = "http://127.0.0.1:8787"
    codex_runtime_bridge_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[4] / "codex-runtime-bridge"
    )
    model_provider: str = "codex"
    codex_approval_policy: str | None = "never"
    codex_sandbox: str | None = "danger-full-access"
    codex_timeout_seconds: float | None = None
    default_user_name: str = "User"
    ui_title: str = "Marrowy"
    secret_key: str = "change-me"
    base_dir: Path = Field(default_factory=lambda: Path.cwd())

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
