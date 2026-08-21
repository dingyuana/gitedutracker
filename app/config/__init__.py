from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlmodel import SQLModel, create_engine
from sqlalchemy.engine import Engine

_settings: Optional[Settings] = None
_engine: Optional[Engine] = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # GitHub
    github_token: str = ""
    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_context_max_chars: int = 12000
    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    # Admin
    admin_password: str = ""
    # Scheduler
    auto_run_time: str = ""
    # DB
    database_url: str = "sqlite:///./data/github_tracker.db"
    # TZ
    tz: str = "Asia/Shanghai"

    @property
    def require_auth(self) -> bool:
        return bool(self.admin_password.strip())


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_engine(url: Optional[str] = None) -> Engine:
    global _engine
    if _engine is None:
        engine_url = url or get_settings().database_url
        _engine = create_engine(engine_url)
    return _engine


def init_db(engine_url: Optional[str] = None) -> None:
    from app.models import SQLModel as _SQLModel
    url = engine_url or get_settings().database_url
    engine = create_engine(url)
    _SQLModel.metadata.create_all(engine)
