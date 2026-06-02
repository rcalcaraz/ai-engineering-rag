"""Pydantic v2 schemas for the ingestion HTTP layer.

Keeping response shapes in one module makes the contract easy to read against
the router code.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.documents.models import DocumentMetadata


class IngestionRunRequest(BaseModel):
    """Body of ``POST /api/v1/ingestion/runs``."""

    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Name of an ``include`` source in the catalog. Anything else "
            "(unknown, review, exclude) is rejected with HTTP 400."
        ),
    )


class IngestionRunResponse(BaseModel):
    """Response of ``POST /api/v1/ingestion/runs``. Returned with HTTP 202."""

    job_id: uuid.UUID
    source_name: str
    status: Literal["pending", "running", "completed", "failed"]


class IngestionJobView(BaseModel):
    """Response of ``GET /api/v1/ingestion/jobs/{job_id}``."""

    job_id: uuid.UUID
    source_name: str
    status: Literal["pending", "running", "completed", "failed"]
    documents_count: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class IngestionDocumentView(BaseModel):
    """One normalized document from a completed ingestion job."""

    id: str
    text: str
    metadata: DocumentMetadata


class IngestionJobDocumentsResponse(BaseModel):
    """Response of ``GET /api/v1/ingestion/jobs/{job_id}/documents``."""

    job_id: uuid.UUID
    source_name: str
    status: Literal["completed"]
    documents: list[IngestionDocumentView]


class IngestionJobNotReadyDetail(BaseModel):
    """HTTP 409 when documents are requested before the job finishes."""

    reason: Literal["job_not_ready"] = "job_not_ready"
    job_id: uuid.UUID
    status: Literal["pending", "running", "failed"]
    error_message: str | None = None
    detail: str
