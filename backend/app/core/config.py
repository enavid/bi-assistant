from __future__ import annotations

from pathlib import Path
from typing import List
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent.parent / ".env",
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

    # App database
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    # HR database
    hr_db_host: str
    hr_db_port: int = 5432
    hr_db_name: str
    hr_db_user: str
    hr_db_password: str

    # CORS
    cors_origins: List[str] = ["http://localhost:5173"]

    # Logging
    log_level: str = "INFO"
    log_dir: str = "logs"
    app_env: str = "development"

    metadata_dir: str = "./metadata"
    current_shamsi_year: int = 1404
    default_execute_sql: bool = False
    enable_llm_sql_fallback: bool = True
    validate_sql_before_execution: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: object) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return []

    @property
    def async_db_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def sync_db_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def hr_db_dsn(self) -> str:
        return (
            f"host={self.hr_db_host} port={self.hr_db_port} "
            f"dbname={self.hr_db_name} user={self.hr_db_user} "
            f"password={self.hr_db_password}"
        )


settings = Settings()
