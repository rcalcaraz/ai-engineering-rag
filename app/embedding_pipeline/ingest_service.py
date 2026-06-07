"""Ingest orchestration: chunk → embed → persist, in ONE transaction."""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.embedding_pipeline.chunking.structural import JSONStructuralChunker
from app.embedding_pipeline.embedder import OpenAIEmbedder
from app.embedding_pipeline.schemas import Budget, IngestResponse
from app.persistence.vector_store.repository import ChunkStore

log = structlog.get_logger()


class DuplicateDocumentError(Exception):
    """A document with the same ``source_path`` is already ingested."""

    def __init__(self, document_id: int) -> None:
        super().__init__(f"Document already ingested (id={document_id})")
        self.document_id = document_id


class RagIngestService:
    """Persists one budget as a document + its embedded chunks."""

    def __init__(
        self,
        chunker: JSONStructuralChunker,
        embedder: OpenAIEmbedder,
        session_factory: async_sessionmaker,
        store: ChunkStore,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._session_factory = session_factory
        self._store = store

    async def ingest(
        self, *, source_path: str, document_type: str, budget: Budget
    ) -> IngestResponse:
        started = time.perf_counter()

        async with self._session_factory() as session, session.begin():
            existing_id = await self._store.find_document_id(session, source_path)
            if existing_id is not None:
                raise DuplicateDocumentError(existing_id)

            chunks = self._chunker.chunk([budget])
            embedded = await asyncio.to_thread(self._embedder.embed_many, chunks)

            document_id = await self._store.persist_document_with_chunks(
                session,
                source_path=source_path,
                document_type=document_type,
                doc_metadata={
                    "budget_id": budget.budget_id,
                    "client_sector": budget.client_metadata.sector,
                    "year": budget.year,
                },
                embedded_chunks=embedded,
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response = IngestResponse(
            document_id=document_id,
            chunks_created=len(embedded),
            embedding_dimension=len(embedded[0].embedding) if embedded else 0,
            ingestion_time_ms=elapsed_ms,
        )
        log.info("rag_ingest_persisted", source_path=source_path, **response.model_dump())
        return response
