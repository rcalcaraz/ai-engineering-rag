# ai-engineering-rag

Base de ingestión y parsing para un sistema RAG (Retrieval-Augmented Generation). Extraída del módulo Session 6 del proyecto `ai-engineering/estimator`.

## Qué es

Este servicio implementa la **primera fase de un pipeline RAG**: convertir fuentes de datos heterogéneas en documentos normalizados (`Document`) listos para chunking e indexación.

Incluye tres capas conceptuales:


| Capa              | Paquete                                            | Responsabilidad                                         |
| ----------------- | -------------------------------------------------- | ------------------------------------------------------- |
| Catálogo          | `app/ingestion/catalog/`                           | Auditoría versionada de fuentes (qué ingerir y por qué) |
| Loaders + Parsers | `app/ingestion/loaders/`, `app/ingestion/parsers/` | Bytes crudos → `list[Document]`                         |
| Cleaning + PII    | `app/ingestion/cleaning/`, `app/ingestion/pii/`    | Validación tabular y pseudonimización GDPR              |


La persistencia (`app/persistence/`) guarda el estado de jobs de ingestión y los mappings de pseudonimización en Postgres.

## Pipeline

```
POST /api/v1/ingestion/runs
  └→ validar fuente en catálogo (decision == include)
  └→ crear job en Postgres (pending)
  └→ BackgroundTask: ingest_source()
       └→ FileSystemLoader → ParserRegistry → list[Document]
       └→ actualizar job (completed / failed)
```

Los documentos parseados **no se persisten** todavía; solo se cuenta cuántos se produjeron. Chunking, embeddings e índice vectorial son el módulo 3.

## Estructura del proyecto

```
app/
├── main.py              # FastAPI + structlog + /health
├── config.py            # Settings (env vars)
├── dependencies.py      # Factories de catálogo, loader, registry
├── routers/ingestion.py # POST /runs, GET /jobs/{id}
├── schemas/ingestion.py # Contratos Pydantic HTTP
├── ingestion/           # Catálogo, loaders, parsers, cleaning, PII
└── persistence/         # SQLAlchemy + repos de jobs/mappings
data/
├── catalog/catalog.yaml # Catálogo versionado de fuentes
└── seed/                # Datos de prueba (budgets JSON, transcripts TXT)
alembic/                 # Migraciones Postgres
tests/                   # Tests unitarios e HTTP
```

## Requisitos

- Docker Compose v2.20+
- [uv](https://docs.astral.sh/uv/) (opcional, para desarrollo local sin Docker)

## Arranque rápido

```bash
cp .env.example .env
docker compose up --build
```

Verificar health:

```bash
curl http://localhost:8000/health
```

Lanzar una ingestión de presupuestos JSON:

```bash
# Crear run (202 Accepted)
curl -X POST http://localhost:8000/api/v1/ingestion/runs \
  -H 'Content-Type: application/json' \
  -d '{"source_name": "presupuestos_json"}'

# Consultar estado (sustituir JOB_ID)
curl http://localhost:8000/api/v1/ingestion/jobs/JOB_ID
```

Con [httpie](https://httpie.io/):

```bash
http POST :8000/api/v1/ingestion/runs source_name=presupuestos_json
http :8000/api/v1/ingestion/jobs/JOB_ID
```

Swagger UI disponible en `http://localhost:8000/docs`.

## API HTTP


| Método | Ruta                              | Descripción                                             |
| ------ | --------------------------------- | ------------------------------------------------------- |
| `GET`  | `/health`                         | Healthcheck del servicio                                |
| `POST` | `/api/v1/ingestion/runs`          | Lanza ingestión async de una fuente `include` → **202** |
| `GET`  | `/api/v1/ingestion/jobs/{job_id}` | Consulta estado del job                                 |


Errores del endpoint de runs:

- Fuente desconocida → **404** `{reason: "unknown_source"}`
- Fuente `review`/`exclude` → **400** `{reason: "source_not_included", decision, decision_reason}`

## Configuración


| Variable                 | Default                                           | Descripción                                      |
| ------------------------ | ------------------------------------------------- | ------------------------------------------------ |
| `APP_ENV`                | `development`                                     | Entorno (`development`, `staging`, `production`) |
| `LOG_LEVEL`              | `DEBUG`                                           | Nivel de log                                     |
| `DATABASE_URL`           | `postgresql+psycopg://rag:rag@localhost:5434/rag` | Conexión Postgres                                |
| `CATALOG_PATH`           | `data/catalog/catalog.yaml`                       | Ruta al catálogo YAML                            |
| `INGESTION_DATA_ROOT`    | `data/seed`                                       | Raíz de datos para `location` del catálogo       |
| `PRESIDIO_SPACY_MODEL`   | `es_core_news_md`                                 | Modelo spaCy para Presidio                       |
| `PSEUDONYM_FAKER_LOCALE` | `es_ES`                                           | Locale Faker para pseudónimos                    |
| `PSEUDONYM_HASH_SALT`    | `change-me-in-prod`                               | Salt HMAC para mappings PII                      |


Dentro de Docker Compose, `DATABASE_URL` se sobreescribe a `rag-postgres:5432`.

## Desarrollo local (sin Docker)

```bash
uv sync
cp .env.example .env

# Postgres debe estar accesible en localhost:5434
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Tests

```bash
# En el host
uv run pytest -v

# Dentro del contenedor
docker compose exec rag bash -c 'pip install pytest pytest-asyncio httpx -q && pytest tests/ -v'
```

## Próximos pasos (módulo 3)

- Chunking de `Document.text`
- Embeddings de chunks
- Activar extensión `pgvector` e índice vectorial
- Persistencia de documentos/chunks
- Endpoint de retrieval / búsqueda semántica
- Cablear cleaning y PII al orchestrator HTTP

