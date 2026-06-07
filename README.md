# ai-engineering-rag

Servicio FastAPI que implementa un pipeline RAG completo en fases: ingestión de
fuentes heterogéneas, normalización de documentos, chunking, generación de
embeddings y persistencia vectorial en Postgres + pgvector con búsqueda semántica.

## Qué hace


| Fase           | Paquete                                            | Responsabilidad                                            |
| -------------- | -------------------------------------------------- | ---------------------------------------------------------- |
| Catálogo       | `app/ingestion/catalog/`                           | Auditoría versionada de fuentes (qué ingerir y por qué)    |
| Ingestión      | `app/ingestion/loaders/`, `app/ingestion/parsers/` | Bytes crudos → `Document` normalizados                     |
| Limpieza y PII | `app/ingestion/cleaning/`, `app/ingestion/pii/`    | Validación tabular y pseudonimización GDPR                 |
| Embeddings     | `app/embedding_pipeline/`                          | Chunking + vectores OpenAI + búsqueda semántica            |
| Persistencia   | `app/persistence/`                                 | Jobs de ingestión, documentos, mappings PII y vector store |


### Chunkers disponibles

Dos estrategias tras la interfaz común `Chunker` (`app/embedding_pipeline/chunking/base.py`):


| Estrategia   | Módulo                              | Comportamiento                                                                        |
| ------------ | ----------------------------------- | ------------------------------------------------------------------------------------- |
| `structural` | `chunking/structural.py`            | Un componente del presupuesto = un chunk, con cabecera de contexto del proyecto padre |
| `fixed_size` | `chunking/strategies/fixed_size.py` | Ventana fija de tokens con solapamiento; baseline para comparar                       |


El endpoint `POST /embeddings/ingest` usa `structural` por defecto.

## Requisitos

- Docker Compose v2.20+
- [uv](https://docs.astral.sh/uv/) (opcional, para ejecutar fuera del contenedor)
- API key de OpenAI (necesaria para embeddings)

## Configuración inicial

```bash
cp .env.example .env
```

Edita `.env` y configura al menos:

```bash
OPENAI_API_KEY=sk-...          # obligatoria para embeddings
EMBEDDING_MODEL=text-embedding-3-small
```

El resto de variables tiene valores por defecto válidos para desarrollo local.

## Arranque

```bash
docker compose up --build
```

El servicio queda disponible en `http://localhost:8000`. Swagger UI en `/docs`.

Si cambias dependencias en `pyproject.toml`, reconstruye la imagen:

```bash
docker compose build rag
```

## Guía paso a paso

Sigue estos pasos en orden para verificar que todo funciona.

### 1. Comprobar que el servicio está vivo

```bash
curl http://localhost:8000/health
```

Respuesta esperada: `{"status":"healthy",...}`.

### 2. Ingerir presupuestos JSON

Lanza una ingestión async de la fuente `presupuestos_json` definida en el catálogo:

```bash
curl -X POST http://localhost:8000/api/v1/ingestion/runs \
  -H 'Content-Type: application/json' \
  -d '{"source_name": "presupuestos_json"}'
```

Guarda el `job_id` de la respuesta (status `202`).

Consulta el estado hasta que pase a `completed`:

```bash
curl http://localhost:8000/api/v1/ingestion/jobs/JOB_ID
```

Recupera los documentos normalizados:

```bash
curl http://localhost:8000/api/v1/ingestion/jobs/JOB_ID/documents
```

Con [httpie](https://httpie.io/):

```bash
http POST :8000/api/v1/ingestion/runs source_name=presupuestos_json
http :8000/api/v1/ingestion/jobs/JOB_ID
http :8000/api/v1/ingestion/jobs/JOB_ID/documents
```

### 3. Persistir presupuestos como vectores

Ingesta un presupuesto histórico (un documento por request). Los chunks y sus
embeddings se persisten en Postgres + pgvector en una sola transacción:

```bash
curl -s -X POST http://localhost:8000/embeddings/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "source_path": "data/budgets_sample.json::BUD-2024-001",
    "document_type": "historical_budget",
    "content": '"$(python3 -c "import json; print(json.dumps(json.load(open(\"data/budgets_sample.json\"))[0]))")"'
  }' | python3 -m json.tool
```

Respuesta esperada (200 OK):

```json
{
  "document_id": 1,
  "chunks_created": 4,
  "embedding_dimension": 1536,
  "ingestion_time_ms": 1240
}
```

Si el `source_path` ya existe → **409** `{"detail": "Document already ingested", "document_id": N}`.

### 4. Búsqueda semántica

```bash
curl -s -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "REST API with OAuth authentication for fintech sector", "k": 5}' \
  | python3 -m json.tool
```

### 5. Script de queries de ejemplo

Ingesta el corpus completo (idempotente) y lanza cinco queries representativas:

```bash
docker compose run --rm rag python scripts/query_examples.py
```

La salida real contra el corpus de ejemplo está en `[output_examples.txt](output_examples.txt)`.

### 6. Sanity check de embeddings (script aislado)

El script `scripts/compare.py` embebe dos textos y calcula similitud coseno
(con la biblioteca estándar, sin numpy ni scikit-learn):

```bash
# Dentro del contenedor
docker compose exec rag python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"

# Fuera del contenedor (requiere uv sync)
uv run python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"
```

Salida esperada:

```
Text A: OAuth 2.0 authentication backend for fintech
Text B: JWT-based authorization service for banking app
Cosine similarity: 0.8421
```

Resultados de las tres parejas de validación documentados en
`app/embedding_pipeline/SANITY_CHECK.md`.

### 7. Probar limpieza tabular (script aislado)

El módulo de cleaning aún no está cableado al endpoint HTTP; se prueba con:

```bash
docker compose exec rag python scripts/demo_cleaning_s06.py
# o: uv run python scripts/demo_cleaning_s06.py
```

Resultado esperado: 6 ficheros entran, el dedup colapsa `BUDGET-2024-0005` → 5
filas; la fila con `total_amount: -50000` se descarta.

### 8. Probar pseudonimización PII (script aislado)

```bash
docker compose exec rag python scripts/demo_pii_s06.py
# o: uv run python scripts/demo_pii_s06.py
```

Pseudonimiza la transcripción de seed con Presidio + spaCy en español. Requiere
el modelo `es_core_news_md` (instalado en la imagen Docker).

### 9. Ejecutar tests

```bash
# En el host
uv run pytest -v

# Dentro del contenedor
docker compose exec rag bash -c 'pip install pytest pytest-asyncio httpx -q && pytest tests/ -v'
```

## API HTTP


| Método | Ruta                                        | Descripción                                                                                          |
| ------ | ------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `GET`  | `/health`                                   | Healthcheck del servicio                                                                             |
| `POST` | `/api/v1/ingestion/runs`                    | Lanza ingestión async → **202**                                                                      |
| `GET`  | `/api/v1/ingestion/jobs/{job_id}`           | Consulta estado del job                                                                              |
| `GET`  | `/api/v1/ingestion/jobs/{job_id}/documents` | Documentos persistidos (job `completed`) → **200**; si no terminó → **409**                          |
| `POST` | `/embeddings/ingest`                        | Persiste un presupuesto como document + chunks → **200**; duplicado → **409**; sin API key → **500** |
| `POST` | `/search`                                   | Búsqueda semántica k-NN por distancia coseno → **200**; sin API key → **500**                        |


Errores del endpoint de ingestión:

- Fuente desconocida → **404** `{reason: "unknown_source"}`
- Fuente `review`/`exclude` → **400** `{reason: "source_not_included", decision, decision_reason}`

## Estructura del proyecto

```
app/
├── main.py                          # FastAPI + structlog + /health
├── config.py                        # Settings (env vars)
├── dependencies.py                  # Factories de catálogo, chunkers, embedder
├── routers/ingestion.py             # Endpoints de ingestión
├── schemas/ingestion.py             # Contratos Pydantic HTTP
├── embedding_pipeline/
│   ├── chunking/
│   │   ├── base.py                  # Interfaz Chunker + count_tokens
│   │   ├── structural.py            # JSONStructuralChunker
│   │   └── strategies/
│   │       └── fixed_size.py        # FixedSizeChunker
│   ├── embedder.py                  # OpenAIEmbedder (text-embedding-3-small)
│   ├── schemas.py                   # Budget, Chunk, Ingest/Search contracts
│   ├── ingest_service.py            # Orquestación chunk → embed → persist
│   ├── retriever.py                 # Búsqueda semántica k-NN
│   ├── router.py                    # POST /embeddings/ingest
│   └── SANITY_CHECK.md
├── persistence/
│   ├── vector_store/                # Modelos ORM + repositorio async (pgvector)
│   └── ...
├── routers/search.py                # POST /search
├── ingestion/                       # Catálogo, loaders, parsers, cleaning, PII
scripts/
├── compare.py                       # Similitud coseno entre dos textos (S07)
├── query_examples.py                # Ingesta corpus + 5 queries semánticas (S08)
├── demo_cleaning_s06.py
└── demo_pii_s06.py
data/
├── catalog/catalog.yaml
├── budgets_sample.json              # Presupuestos para /embeddings/ingest
└── seed/                            # Datos de prueba (budgets, transcripts)
alembic/                             # Migraciones Postgres
tests/
```

## Variables de entorno


| Variable                 | Default                                           | Descripción                                        |
| ------------------------ | ------------------------------------------------- | -------------------------------------------------- |
| `APP_ENV`                | `development`                                     | Entorno (`development`, `staging`, `production`)   |
| `LOG_LEVEL`              | `DEBUG`                                           | Nivel de log                                       |
| `OPENAI_API_KEY`         | —                                                 | Requerida para `/embeddings/ingest` y `compare.py` |
| `EMBEDDING_MODEL`        | `text-embedding-3-small`                          | Modelo de embeddings OpenAI                        |
| `DATABASE_URL`           | `postgresql+psycopg://rag:rag@localhost:5434/rag` | Conexión Postgres                                  |
| `CATALOG_PATH`           | `data/catalog/catalog.yaml`                       | Ruta al catálogo YAML                              |
| `INGESTION_DATA_ROOT`    | `data/seed`                                       | Raíz de datos para `location` del catálogo         |
| `PRESIDIO_SPACY_MODEL`   | `es_core_news_md`                                 | Modelo spaCy para Presidio                         |
| `PSEUDONYM_FAKER_LOCALE` | `es_ES`                                           | Locale Faker para pseudónimos                      |
| `PSEUDONYM_HASH_SALT`    | `change-me-in-prod`                               | Salt HMAC para mappings PII                        |


Dentro de Docker Compose, `DATABASE_URL` se sobreescribe a `rag-postgres:5432`.

## Desarrollo local (sin Docker)

```bash
uv sync
cp .env.example .env
# Edita .env con OPENAI_API_KEY

# Postgres debe estar accesible en localhost:5434
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Sesión 8 — Persistencia vectorial y búsqueda semántica

El pipeline deja de devolver vectores por HTTP y los persiste en Postgres +
pgvector (`pgvector/pgvector:pg16`, servicio `rag-postgres` en compose). Schema
gestionado con Alembic (`alembic/versions/0003_session8_pgvector.py`: extensión
`vector` + tablas `documents` y `chunks`). El stack async (`asyncpg`) convive
con el sync de la S06: una sola `DATABASE_URL`, el engine async deriva el driver.

### Decisiones de schema

- **Dos tablas y no una.** Un presupuesto produce N chunks: es un uno-a-muchos real. Una tabla única duplicaría la metadata del documento en cada fila y perdería integridad referencial. Con `ON DELETE CASCADE`, borrar un presupuesto elimina sus chunks automáticamente; `documents` posee la procedencia (`source_path`, `ingested_at`), `chunks` posee los vectores.
- `**metadata` como JSONB y no columnas tipadas.** Lo estable (tipo de documento, tipo de chunk, fechas) va en columnas tipadas; lo que el chunker puede enriquecer (sector, tecnologías, horas) va a JSONB. El índice GIN permite consultar por claves arbitrarias sin una migración por cada clave nueva.
- `**cosine_distance` y no L2 ni inner product.** Los embeddings de OpenAI vienen normalizados, así que el ranking sería equivalente; usamos coseno por convención RAG y para quedar alineados con la operator class `vector_cosine_ops` del índice HNSW que se añade en el directo. Si la query usa un operador y el índice está construido con otra operator class, Postgres ignora el índice en silencio y cae a sequential scan.
- **Sin índice vectorial todavía (deliberado).** Con el corpus de ejemplo el sequential scan responde en pocos cientos de ms y es el baseline contra el que el directo mide el impacto del HNSW.

**Fuera de scope (se construye en el directo):** índices vectoriales (HNSW/IVFFlat), filtros por metadata en SQL, búsqueda híbrida (full-text + vector) y tuning de Postgres.