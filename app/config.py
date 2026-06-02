from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "DEBUG"

    DATABASE_URL: str = "postgresql+psycopg://rag:rag@localhost:5434/rag"
    CATALOG_PATH: Path = Path("data/catalog/catalog.yaml")
    INGESTION_DATA_ROOT: Path = Path("data/seed")
    PRESIDIO_SPACY_MODEL: str = "es_core_news_md"
    PSEUDONYM_FAKER_LOCALE: str = "es_ES"
    PSEUDONYM_HASH_SALT: str = "change-me-in-prod"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()
