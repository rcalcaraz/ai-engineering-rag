"""Ingestion HTTP surface: runs, job status, persisted documents.

The router is intentionally thin: it validates the source against the catalog,
records the job row, dispatches the orchestrator as a BackgroundTask, and
returns 202 immediately. All ingestion logic lives in
``app.ingestion.orchestrator`` — the router never imports parsers.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import (
    get_catalog,
    get_filesystem_loader,
    get_parser_registry,
)
from app.ingestion.catalog.models import CatalogDecision, DataCatalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.orchestrator import IngestionRejected, ingest_source
from app.ingestion.parsers.registry import ParserRegistry
from app.persistence.database import SessionLocal, get_session
from app.persistence.repositories.documents import DocumentsRepository
from app.persistence.repositories.jobs import JobsRepository
from app.schemas.ingestion import (
    IngestionDocumentView,
    IngestionJobDocumentsResponse,
    IngestionJobNotReadyDetail,
    IngestionJobView,
    IngestionRunRequest,
    IngestionRunResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


def _run_in_background(
    *,
    job_id: uuid.UUID,
    source_name: str,
    catalog: DataCatalog,
    loader: FileSystemLoader,
    registry: ParserRegistry,
) -> None:
    """BackgroundTask body. Owns its own Session — request session is closed."""
    session = SessionLocal()
    try:
        jobs_repo = JobsRepository(session)
        documents_repo = DocumentsRepository(session)
        ingest_source(
            catalog=catalog,
            source_name=source_name,
            loader=loader,
            registry=registry,
            jobs_repo=jobs_repo,
            job_id=job_id,
            documents_repo=documents_repo,
        )
    except Exception as exc:  # noqa: BLE001
        # The orchestrator already wrote the failure row; we just log loudly.
        log.error(
            "ingestion_background_failed",
            job_id=str(job_id),
            source_name=source_name,
            error=str(exc)[:400],
        )
    finally:
        session.close()


@router.post(
    "/runs",
    response_model=IngestionRunResponse,
    status_code=202,
)
def create_ingestion_run(
    request: IngestionRunRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    catalog: DataCatalog = Depends(get_catalog),
    loader: FileSystemLoader = Depends(get_filesystem_loader),
    registry: ParserRegistry = Depends(get_parser_registry),
) -> IngestionRunResponse:
    source = catalog.find(request.source_name)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "unknown_source", "source_name": request.source_name},
        )
    if source.decision is not CatalogDecision.INCLUDE:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "source_not_included",
                "source_name": request.source_name,
                "decision": source.decision.value,
                "decision_reason": source.decision_reason,
            },
        )

    repo = JobsRepository(session)
    job = repo.create(source_name=request.source_name)

    background.add_task(
        _run_in_background,
        job_id=job.job_id,
        source_name=request.source_name,
        catalog=catalog,
        loader=loader,
        registry=registry,
    )
    return IngestionRunResponse(
        job_id=job.job_id, source_name=job.source_name, status=job.status
    )


@router.get("/jobs/{job_id}", response_model=IngestionJobView)
def get_ingestion_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> IngestionJobView:
    job = JobsRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return IngestionJobView(
        job_id=job.job_id,
        source_name=job.source_name,
        status=job.status,
        documents_count=job.documents_count,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get(
    "/jobs/{job_id}/documents",
    response_model=IngestionJobDocumentsResponse,
    responses={
        409: {
            "description": "Job not completed yet or failed",
            "model": IngestionJobNotReadyDetail,
        },
    },
)
def get_ingestion_job_documents(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> IngestionJobDocumentsResponse:
    jobs_repo = JobsRepository(session)
    job = jobs_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "completed":
        detail = IngestionJobNotReadyDetail(
            job_id=job.job_id,
            status=job.status,
            error_message=job.error_message,
            detail=(
                "Documents are available only after a successful run "
                f"(current status: {job.status!r})."
            ),
        )
        raise HTTPException(status_code=409, detail=detail.model_dump(mode="json"))

    documents = DocumentsRepository(session).list_by_job_id(job_id)
    return IngestionJobDocumentsResponse(
        job_id=job.job_id,
        source_name=job.source_name,
        status="completed",
        documents=[
            IngestionDocumentView(
                id=doc.id,
                text=doc.text,
                metadata=doc.metadata,
            )
            for doc in documents
        ],
    )


# The IngestionRejected exception is informational here — the router itself
# performs the same validation upstream. Imports kept for the orchestrator
# entrypoint when called from a script.
__all__ = ["router", "IngestionRejected"]
