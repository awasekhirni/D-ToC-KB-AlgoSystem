SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
BACKEND := $(COMPOSE) exec -T api

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Lifecycle --------------------------------------------------------------
.PHONY: up
up: ## Start all services (build if needed)
	$(COMPOSE) up -d --build
	@echo "API:      http://localhost:8000/docs"
	@echo "Console:  http://localhost:3000"

.PHONY: down
down: ## Stop services (keeps volumes)
	$(COMPOSE) down

.PHONY: reset
reset: ## WARNING: Stop services and DELETE all data volumes
	@read -p "This will delete all data. Continue? [y/N] " ok; \
	[[ "$$ok" == "y" ]] || { echo "Aborted."; exit 1; }
	$(COMPOSE) down -v

.PHONY: restart
restart: ## Restart API and workers (no volume changes)
	$(COMPOSE) restart api worker beat

.PHONY: logs
logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

# --- Database ---------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply Alembic migrations
	$(BACKEND) alembic upgrade head

.PHONY: migration
migration: ## Create a new migration (m="description")
	@test -n "$(m)" || { echo "Usage: make migration m='description'"; exit 1; }
	$(BACKEND) alembic revision --autogenerate -m "$(m)"

.PHONY: migrate-down
migrate-down: ## Roll back one migration
	$(BACKEND) alembic downgrade -1

.PHONY: shell-db
shell-db: ## psql into postgres
	$(COMPOSE) exec postgres psql -U tockb tockb

.PHONY: shell-api
shell-api: ## Python REPL inside the API container
	$(BACKEND) python

.PHONY: seed-root
seed-root: ## Create a root ToC node and print its ID
	$(BACKEND) python -c "import asyncio; from src.scripts.seed import main; asyncio.run(main())"

# --- Tests ------------------------------------------------------------------
.PHONY: test-unit
test-unit: ## Fast unit tests (no external deps)
	$(BACKEND) pytest tests/unit -q

.PHONY: test-int
test-int: ## Integration tests (testcontainers + VCR)
	$(BACKEND) pytest tests/integration -q

.PHONY: test
test: ## Full test suite with coverage
	$(BACKEND) pytest --cov=src --cov-report=term-missing

# --- Quality ----------------------------------------------------------------
.PHONY: lint
lint: ## Ruff + mypy
	$(BACKEND) ruff check src tests
	$(BACKEND) mypy src

.PHONY: fmt
fmt: ## Auto-format
	$(BACKEND) ruff format src tests
	$(BACKEND) ruff check --fix src tests

# --- Docs -------------------------------------------------------------------
.PHONY: openapi
openapi: ## Regenerate docs/openapi.json from the live FastAPI app
	$(BACKEND) python -c "import json; from src.api.main import app; \
		print(json.dumps(app.openapi(), indent=2))" > docs/openapi.json
