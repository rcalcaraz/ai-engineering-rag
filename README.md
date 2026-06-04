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
       └→ guardar documentos en Postgres (`ingestion_documents`)
       └→ actualizar job (completed / failed)
```

Los documentos parseados se persisten por job y se consultan con
`GET /api/v1/ingestion/jobs/{job_id}/documents`. Chunking, embeddings e índice
vectorial son el módulo 3.

## Estructura del proyecto

```
app/
├── main.py              # FastAPI + structlog + /health
├── config.py            # Settings (env vars)
├── dependencies.py      # Factories de catálogo, loader, registry
├── routers/ingestion.py # POST /runs, GET /jobs/{id}, GET /jobs/{id}/documents
├── schemas/ingestion.py # Contratos Pydantic HTTP
├── ingestion/           # Catálogo, loaders, parsers, cleaning, PII
└── persistence/         # SQLAlchemy + repos de jobs/mappings
scripts/                 # Demos de cleaning y PII (Session 6, sin HTTP)
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

# Ver documentos normalizados (solo si status=completed)
curl http://localhost:8000/api/v1/ingestion/jobs/JOB_ID/documents
```

Con [httpie](https://httpie.io/):

```bash
http POST :8000/api/v1/ingestion/runs source_name=presupuestos_json
http :8000/api/v1/ingestion/jobs/JOB_ID
http :8000/api/v1/ingestion/jobs/JOB_ID/documents
```

Swagger UI disponible en `http://localhost:8000/docs`.

## API HTTP


| Método | Ruta                              | Descripción                                             |
| ------ | --------------------------------- | ------------------------------------------------------- |
| `GET`  | `/health`                         | Healthcheck del servicio                                |
| `POST` | `/api/v1/ingestion/runs`          | Lanza ingestión async de una fuente `include` → **202** |
| `GET`  | `/api/v1/ingestion/jobs/{job_id}` | Consulta estado del job                                 |
| `GET`  | `/api/v1/ingestion/jobs/{job_id}/documents` | Lista `Document` persistidos (job `completed`) → **200**; si no terminó → **409** |


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

## Scripts de demo (Session 6)

Los módulos `cleaning` y `pii` **aún no están cableados** al orchestrator HTTP
(ver [Próximos pasos](#próximos-pasos-módulo-3)). Estos scripts permiten
probarlos de forma aislada sobre el corpus de seed, igual que en la sesión en
vivo.

### `scripts/demo_cleaning_s06.py`

Carga todos los JSON de `data/seed/budgets/`, aplica limpieza tabular
(`clean_budget_records`) y validación con Pandera (`validate_with_policy`), e
imprime el informe de partición (válidas / cuarentena / descartadas).

Resultado esperado:

- 6 ficheros entran; el dedup colapsa `BUDGET-2024-0005` → 5 filas.
- La fila con `total_amount: -50000` se descarta; el resto pasa o va a cuarentena.

```bash
# En el host (requiere uv sync previo)
uv run python scripts/demo_cleaning_s06.py

# Dentro del contenedor (con docker compose up)
docker compose exec rag python scripts/demo_cleaning_s06.py
```

### `scripts/demo_pii_s06.py`

Pseudonimiza la transcripción `transcripcion_2025-02-03_betanorte.txt` con
Presidio + spaCy en español (`es_core_news_md`) y los recognizers custom
(`BUDGET_ID`, `CLIENT_CODE`). Usa `InMemoryMappingStore` (sin Postgres) para
mostrar consistencia: mismo valor original → mismo pseudónimo.

Requiere el modelo spaCy español (instalado en la imagen Docker o vía
`python -m spacy download es_core_news_md` en local).

```bash
uv run python scripts/demo_pii_s06.py

docker compose exec rag python scripts/demo_pii_s06.py
```

Si `PSEUDONYM_HASH_SALT` no está definido, el script usa un salt de demo
(`demo-salt`). En producción, configúralo en `.env`.

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
- Persistencia de chunks (documentos ya por job en `ingestion_documents`)
- Endpoint de retrieval / búsqueda semántica
- Cablear cleaning y PII al orchestrator HTTP

