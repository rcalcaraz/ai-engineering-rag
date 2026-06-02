"""FastAPI dependency factories for shared singletons."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.ingestion.catalog import DataCatalog, load_catalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.parsers.registry import ParserRegistry, default_registry


@lru_cache
def get_catalog() -> DataCatalog:
    """Load and cache the data-source catalog.

    The catalog is read once at startup. Re-reading would invalidate the
    decisions baked into the running pipeline; rolling a new catalog version
    requires a process restart by design.
    """
    settings = get_settings()
    return load_catalog(settings.CATALOG_PATH)


@lru_cache
def get_filesystem_loader() -> FileSystemLoader:
    settings = get_settings()
    return FileSystemLoader(data_root=settings.INGESTION_DATA_ROOT)


@lru_cache
def get_parser_registry() -> ParserRegistry:
    """Registry of parsers available in this branch."""
    return default_registry()


def build_pseudonymizer(session):
    """Build a :class:`ConsistentPseudonymizer` backed by Postgres.

    Not a singleton — the mapping store wraps a Session, so callers (scripts,
    BackgroundTasks, tests) must pass their own.
    """
    from app.ingestion.pii import (
        ConsistentPseudonymizer,
        PostgresMappingStore,
        build_analyzer,
    )

    settings = get_settings()
    return ConsistentPseudonymizer(
        analyzer=build_analyzer(),
        mapping_store=PostgresMappingStore(session),
        salt=settings.PSEUDONYM_HASH_SALT,
        faker_locale=settings.PSEUDONYM_FAKER_LOCALE,
        language="es",
    )
