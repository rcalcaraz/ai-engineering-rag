"""Repository for ``Document`` rows produced by a completed ingestion job."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.documents.models import Document, DocumentMetadata
from app.persistence.models import IngestionDocumentRow


class DocumentsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_for_job(self, job_id: uuid.UUID, documents: list[Document]) -> None:
        for doc in documents:
            self._session.add(
                IngestionDocumentRow(
                    job_id=job_id,
                    document_id=doc.id,
                    text=doc.text,
                    metadata_json=doc.metadata.model_dump(mode="json"),
                )
            )
        self._session.commit()

    def list_by_job_id(self, job_id: uuid.UUID) -> list[Document]:
        rows = (
            self._session.execute(
                select(IngestionDocumentRow)
                .where(IngestionDocumentRow.job_id == job_id)
                .order_by(IngestionDocumentRow.document_id)
            )
            .scalars()
            .all()
        )
        return [_row_to_document(row) for row in rows]


def _row_to_document(row: IngestionDocumentRow) -> Document:
    return Document(
        id=row.document_id,
        text=row.text,
        metadata=DocumentMetadata.model_validate(row.metadata_json),
    )
