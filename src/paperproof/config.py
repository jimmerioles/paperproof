"""Application settings, loaded from environment with the PAPERPROOF_ prefix."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPERPROOF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8000

    # Retrieval
    top_k: int = 6
    candidate_k: int = 48
    chunk_chars: int = 900
    chunk_overlap_chars: int = 160
    embedder: str = "hash"

    # OCR
    ocr: Literal["auto", "tesseract", "off"] = "auto"
    ocr_dpi: int = 300
    ocr_min_chars: int = 40
    ocr_low_confidence: float = 60.0

    # Authentication
    env: Literal["dev", "prod"] = "dev"
    auth_disabled: bool = False
    session_secret: str | None = None
    session_ttl_seconds: int = 12 * 60 * 60
    login_max_attempts: int = 5
    login_window_seconds: int = 5 * 60
    login_lockout_seconds: int = 5 * 60

    # Observability
    log_level: str = "INFO"
    health_min_free_mb: int = 100
    llm_input_cost_per_million: float = 0.40
    llm_output_cost_per_million: float = 1.60

    # Extraction
    extractor: str = "auto"  # auto | rules | llm
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    llm_timeout: float = 60.0
    llm_temperature: float = 0.0
    llm_retries: int = 1

    # Limits
    max_upload_mb: int = 50
    render_scale: int = 2

    @property
    def db_path(self) -> Path:
        return self.data_dir / "paperproof.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def render_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def secure_cookies(self) -> bool:
        return self.env == "prod"

    @model_validator(mode="after")
    def _validate_auth(self) -> Settings:
        if self.auth_disabled and self.env != "dev":
            raise ValueError("PAPERPROOF_AUTH_DISABLED is only allowed when PAPERPROOF_ENV=dev.")
        if self.session_ttl_seconds < 60:
            raise ValueError("PAPERPROOF_SESSION_TTL_SECONDS must be at least 60.")
        return self

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.render_dir, self.sample_dir):
            path.mkdir(parents=True, exist_ok=True)

    def llm_configured(self) -> bool:
        return bool(self.llm_base_url)

    def use_llm(self) -> bool:
        if self.extractor == "rules":
            return False
        if self.extractor == "llm":
            return self.llm_configured()
        return self.llm_configured()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
