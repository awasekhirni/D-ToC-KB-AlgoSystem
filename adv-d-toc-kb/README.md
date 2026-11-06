# Adv-D-ToC-KB

A self-organising, LLM-orchestrated knowledge base. Ingests unstructured
text, routes it into a depth-bounded tree (a Table of Contents), splits
overloaded nodes via embedding clustering, audits for semantic drift, and
overlays aliases to form a navigable DAG — all without ever feeding raw
corpora to the primary LLM.

> Design premise: the LLM is never trusted to see more than what it needs.
> Routing scores go through centroids; restructuring goes through cluster
> summaries; audits go through random samples. Context windows are a scarce
> resource, and this system treats them that way.

---

## Table of Contents

- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [API Surface](#api-surface)
- [Design Decisions](#design-decisions)
- [Operational Notes](#operational-notes)
- [Project Layout](#project-layout)
- [Logging & Observability](#logging--observability)

---

## Architecture

```
┌─────────────────────┐   REST    ┌───────────────────────────────┐
│  React Console      │<─────────>│  FastAPI (auth + envelope)    │
└─────────────────────┘           └──────────────┬────────────────┘
                                                 │
                          ┌──────────────────────┼──────────────────────┐
                          ▼                      ▼                      ▼
                    ┌──────────┐          ┌────────────┐        ┌──────────────┐
                    │ Routing  │          │Restructure │        │    Audit     │
                    │  Engine  │          │  Engine    │        │   Engine     │
                    └────┬─────┘          └──────┬─────┘        └──────┬───────┘
                         │                       │                     │
                         └───────────┬───────────┴─────────┬───────────┘
                                     ▼                     ▼
                          ┌────────────────────┐  ┌───────────────────┐
                          │  PostgreSQL 16     │  │  OpenAI (embed +  │
                          │  + pgvector        │  │  chat, singleton) │
                          │  (source of truth) │  └───────────────────┘
                          └─────────┬──────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  Celery + Redis    │
                          │  (audit sweep,     │
                          │   restructure)     │
                          └────────────────────┘
```

Four engines, one source of truth, one vendor boundary:

| Engine | Responsibility | Spec phase |
|---|---|---|
| RoutingEngine | Ingest -> find best child by centroid -> recurse; spillover / pivot at max depth | 2 |
| RestructureEngine | K-Means over chunks -> cluster summaries -> LLM proposes sub-ToC from summaries only -> re-route chunks by cosine | 3 |
| AuditEngine | Sample chunks -> LLM verifies summary -> rewrite if drifted; KNN -> LLM detects cross-branch need -> create alias; resolve broken chains | 4 |
| AliasCreationEngine | Enforce 5 invariants -> create alias node with `points_to_id` | 4 |

See [`docs/architecture.md`](docs/architecture.md) for the full walkthrough.

---

## Quickstart

### Prerequisites

- Docker 24+ and Docker Compose v2
- An OpenAI API key (`TOCKB_OPENAI_API_KEY`)
- 4 GB RAM minimum (Postgres + pgvector + Redis + Python + Node)

### Run with Docker (recommended)

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env -- set TOCKB_OPENAI_API_KEY and TOCKB_ADMIN_TOKEN

# 2. Bootstrap (builds images, starts services, runs migrations, seeds a root)
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh

# 3. Open the console
open http://localhost:3000
```

The bootstrap script prints a root node ID at the end. Paste it into the
console's "Root ID" field to load the initial tree.

### Run locally (without Docker)

See [Local Development](#local-development) below.

### Manual operations

```bash
make up        # start all services
make migrate   # run Alembic migrations
make down      # stop services (preserves volumes)
make reset     # destroy volumes and recreate (WARNING: wipes data)
make logs      # tail all logs
make shell-api # exec into the API container
make shell-db  # psql into postgres
```

---

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start postgres + redis (you can use docker compose for just these)
docker compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start the API
uvicorn src.api.main:app --reload --port 8000

# In another terminal, start a worker
celery -A src.workers.celery_app worker --loglevel=INFO

# And the beat scheduler
celery -A src.workers.celery_app beat --loglevel=INFO
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # starts Vite on http://localhost:5173
```

---

## Configuration

All env vars prefixed with `TOCKB_`. Every value is validated at process
startup; the container will refuse to boot if invalid.

| Variable | Default | Purpose |
|---|---|---|
| `TOCKB_DATABASE_URL` | — | Required. `postgresql+asyncpg://user:pass@host:5432/db` |
| `TOCKB_REDIS_URL` | `redis://redis:6379/0` | Celery broker + result backend |
| `TOCKB_OPENAI_API_KEY` | — | Required when `EMBEDDING_PROVIDER=openai` |
| `TOCKB_ADMIN_TOKEN` | unset | Bearer token for `/audit/` and `/alias/`. Set in production. |
| `TOCKB_MAX_DEPTH` | `5` | Hard ceiling on tree depth (1-10) |
| `TOCKB_MAX_ALIAS_HOPS` | `3` | Transitive alias resolution cap |
| `TOCKB_MAX_TOKENS_PER_NODE` | `50000` | Restructure trigger threshold |
| `TOCKB_MAX_VARIANCE_THRESHOLD` | `0.75` | Restructure trigger (semantic variance) |
| `TOCKB_SIMILARITY_THRESHOLD` | `0.65` | Routing: descend if child centroid >= this |
| `TOCKB_MAX_DEPTH_STRATEGY` | `spillover` | `spillover` or `pivot` |
| `TOCKB_KMEANS_MAX_CLUSTERS` | `7` | Upper bound on cluster count during restructure |
| `TOCKB_AUDIT_INTERVAL_DAYS` | `30` | Nodes older than this enter the sweep |
| `TOCKB_AUDIT_SAMPLE_SIZE` | `10` | Chunks sampled per audit |
| `TOCKB_AUDIT_BATCH_SIZE` | `100` | Nodes processed per sweep tick |
| `TOCKB_ALIAS_DISCOVERY_ENABLED` | `true` | Enable KNN-based alias creation during audit |
| `TOCKB_ALIAS_SIMILARITY_THRESHOLD` | `0.80` | Minimum cross-branch similarity to consider an alias |
| `TOCKB_EMBEDDING_MODEL` | `text-embedding-3-large` | OpenAI embedding model |
| `TOCKB_EMBEDDING_DIMENSIONS` | `1536` | 1536 or 3072 — changing this requires a full re-index |
| `TOCKB_LLM_MODEL` | `gpt-4o-mini` | Model for naming, sub-ToC, drift verify, alias detect |
| `TOCKB_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TOCKB_LOG_FORMAT` | `json` | `json` or `text` |

---

## Running Tests

```bash
# Unit tests (no external deps -- ~5s)
make test-unit

# Integration tests (testcontainers Postgres+pgvector, VCR-mocked OpenAI)
make test-int

# Full suite + coverage
make test
```

Integration tests use recorded cassettes for all OpenAI calls — CI never
hits the API. To regenerate cassettes (only when changing prompts):

```bash
VCR_RECORD=all make test-int
```

---

## API Surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness |
| `GET` | `/toc/{root_id}` | public | Full subtree (recursive CTE, truncated at 5k) |
| `POST` | `/ingest` | public | Route new content; returns routed path + flags |
| `GET` | `/audit/log/{node_id}` | admin | Audit timeline for a node |
| `POST` | `/audit/run` | admin | Trigger sweep (`?node_id=X` for single) |
| `POST` | `/alias` | admin | Manually create an alias |

`GET /docs` and `/openapi.json` are served by FastAPI.

---

## Design Decisions

Full ADRs in [`docs/adr/`](docs/adr/).

- **ADR-0001** — pgvector over in-memory embeddings. IVFFlat indexes give
  ANN search for KNN queries and single-round-trip centroid aggregation.
- **ADR-0002** — Plain `asyncio` state machine over LangGraph. Typed
  protocols make the domain engine fully testable without an LLM.
- **ADR-0003** — Alias DAG overlay via `is_alias` + `points_to_id`.
  Physical tree stays strict; alias nodes form the DAG.
- **ADR-0004** — Spillover + pivot dual max-depth strategies. Pivot fires
  once per path then falls back to spillover — guaranteed termination.
- **ADR-0005** — Per-node commit in workers. One bad node cannot poison a
  100-node batch.
- **ADR-0006** — Postgres is the only source of truth. Redis is a broker,
  not a store.

---

## Operational Notes

### Backup

Everything that matters is in Postgres. Standard `pg_dump` suffices:

```bash
docker compose exec postgres pg_dump -U tockb tockb > backup-$(date +%F).sql
```

### Key rotation

Changing `TOCKB_EMBEDDING_MODEL` or `TOCKB_EMBEDDING_DIMENSIONS` requires a
full re-index (see DEF-001 in `ERROR_INVENTORY.md`).

Changing `TOCKB_ADMIN_TOKEN` takes effect after API restart.

### Monitoring signals

- `audit_log` event counts by `event_type` — spikes in `BROKEN_ALIAS_CHAIN`
  indicate alias-overlay corruption.
- `content_chunks` row count per node — consistently near
  `MAX_TOKENS_PER_NODE` suggests restructure thresholds need retuning.
- Celery task durations — restructure tasks >30s typically mean clustering
  ran with too many clusters.

### When the LLM is down

- `/ingest` returns 502. Existing tree remains readable via `/toc/`.
- Audit sweeps fail per-node; sweep result reports `errors > 0`.
- Restructure workers retry 3x with exponential backoff.
- Nothing is lost — writes are transactional; only the LLM path fails.

---

## Logging & Observability

The system uses structured JSON logging by default (configurable to text
via `TOCKB_LOG_FORMAT`). Every function in the domain layer logs:

- **Entry/exit** at DEBUG level with function name and key parameters
- **Errors** at ERROR level with full context (request_id, node_id, etc.)
- **Audit events** at INFO level (these also persist to `audit_log`)

Log format (JSON):

```json
{
  "timestamp": "2026-11-06T12:00:00Z",
  "level": "INFO",
  "logger": "src.core.engine.routing",
  "message": "Routed content to node",
  "request_id": "uuid",
  "node_id": "uuid",
  "event_type": "NODE_ROUTED"
}
```

To change log level at runtime (without restart), set `TOCKB_LOG_LEVEL`
and restart the process. For fine-grained control, individual loggers
can be configured in `src/observability/logging.py`.

---

## Project Layout

```
adv-d-toc-kb/
├── backend/            # FastAPI + engines + workers
│   ├── src/
│   │   ├── config/     # Settings
│   │   ├── core/       # Domain engines, LLM, clustering
│   │   ├── db/         # Models, repositories, migrations
│   │   ├── api/        # Routes, middleware, deps
│   │   ├── workers/    # Celery tasks
│   │   └── observability/  # Logging, metrics
│   └── tests/          # Unit + integration
├── frontend/           # React console
├── docs/
│   ├── adr/           # Architecture Decision Records
│   └── architecture.md
├── scripts/           # bootstrap.sh, wait-for-it.sh
├── docker-compose.yml
├── Makefile
└── .env.example
```

See [`docs/architecture.md`](docs/architecture.md) for the full module map.

---

## License

TBD.
