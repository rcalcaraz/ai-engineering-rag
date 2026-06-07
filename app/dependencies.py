"""FastAPI dependency factories for shared singletons."""

from __future__ import annotations

from functools import lru_cache

import structlog
from openai import OpenAI

from app.config import get_settings
from app.embedding_pipeline.chunking.structural import JSONStructuralChunker
from app.embedding_pipeline.chunking.strategies.fixed_size import FixedSizeChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder
from app.embedding_pipeline.ingest_service import RagIngestService
from app.embedding_pipeline.retriever import SemanticRetriever
from app.ingestion.catalog import DataCatalog, load_catalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.parsers.registry import ParserRegistry, default_registry
from app.persistence.database import get_async_session_factory
from app.persistence.vector_store.repository import ChunkStore

log = structlog.get_logger()


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


@lru_cache
def get_openai_client() -> OpenAI | None:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return None
    return OpenAI(api_key=settings.OPENAI_API_KEY)


@lru_cache
def get_chunker() -> JSONStructuralChunker:
    return JSONStructuralChunker()


@lru_cache
def get_fixed_size_chunker() -> FixedSizeChunker:
    return FixedSizeChunker()


@lru_cache
def get_embedder() -> OpenAIEmbedder | None:
    settings = get_settings()
    client = get_openai_client()
    if client is None:
        log.warning("embedder_disabled", reason="no_openai_key")
        return None
    return OpenAIEmbedder(client=client, model=settings.EMBEDDING_MODEL)


# --- Session 8: pgvector persistence + semantic search ---------------------


@lru_cache
def get_chunk_store() -> ChunkStore:
    return ChunkStore()


@lru_cache
def get_rag_ingest_service() -> RagIngestService | None:
    embedder = get_embedder()
    if embedder is None:
        return None
    return RagIngestService(
        chunker=get_chunker(),
        embedder=embedder,
        session_factory=get_async_session_factory(),
        store=get_chunk_store(),
    )


@lru_cache
def get_semantic_retriever() -> SemanticRetriever | None:
    embedder = get_embedder()
    if embedder is None:
        return None
    return SemanticRetriever(
        embedder=embedder,
        session_factory=get_async_session_factory(),
        store=get_chunk_store(),
    )


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
