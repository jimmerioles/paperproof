"""Application settings, loaded from environment with the PAPERPROOF_ prefix."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
