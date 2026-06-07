import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.embedding_pipeline.router import router as embeddings_router
from app.routers import ingestion
from app.routers import search


def configure_logging() -> None:
    """Set up structlog: JSON in production, human-readable in development."""
    settings = get_settings()

    if settings.APP_ENV == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    configure_logging()
    log = structlog.get_logger()
    settings = get_settings()
    try:
        from app.dependencies import get_catalog

        catalog = get_catalog()
        log.info(
            "catalog_loaded",
            version=catalog.version,
            sources_total=len(catalog.sources),
            sources_included=len(catalog.included_sources()),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("catalog_load_failed", error=str(exc)[:400])
    log.info("application_started", environment=settings.APP_ENV)
    yield
    log.info("application_shutdown")


app = FastAPI(
    title="RAG Ingest & Parser Service",
    description="Catalog-driven document ingestion base for RAG systems",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.include_router(ingestion.router)
app.include_router(embeddings_router)
app.include_router(search.router)


@app.get("/health")
async def health_check() -> dict:
    """Return service health status."""
    settings = get_settings()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.APP_ENV,
    }
