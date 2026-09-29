from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8066
    data_dir: Path = Path("data")
    web_dist: Path | None = None
    demo_mode: bool = False
    enable_scheduler: bool = True
    log_level: str = "INFO"
    app_secret_key: str = ""

    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""

    # defaults for settings sections; the DB (app_settings) overrides at runtime
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_use_tls: bool = True
    lumirss_base_url: str = ""
    lumirss_token: str = ""
    lumirss_inbox_endpoint: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "biliup.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    return settings


def reset_settings_cache() -> None:
    """Used by tests to re-read env."""
    get_settings.cache_clear()
    os.environ.pop("_BILIUP_TEST", None)
