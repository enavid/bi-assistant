from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama
    ollama_url: str
    ollama_tags_url: str
    model_name: str
    model_temperature: float = 0.4
    model_top_p: float = 0.5
    model_timeout: int = 120

    # Storage
    data_dir: Path = Path("./data")

    # PostgreSQL
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    # CORS — comma-separated string in .env, parsed to list
    cors_origins: List[str] = ["http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return []

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def workspace_file(self) -> Path:
        return self.data_dir / "workspace.json"

    @property
    def sessions_file(self) -> Path:
        return self.data_dir / "sessions.json"


settings = Settings()
