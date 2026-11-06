#!/usr/bin/env bash
# One-shot bootstrap: check prerequisites, start services, run migrations,
# seed a root node, print the ID for the console.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\033[36m[bootstrap]\033[0m %s\n' "$1"; }
die() { printf '\033[31m[bootstrap]\033[0m %s\n' "$1" >&2; exit 1; }

# --- Prerequisites -----------------------------------------------------------
command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose v2 required"

[[ -f .env ]] || { log "No .env found; copying from .env.example"; cp .env.example .env; }

if ! grep -q '^TOCKB_OPENAI_API_KEY=sk-' .env; then
    die "Edit .env and set TOCKB_OPENAI_API_KEY before running again."
fi

if ! grep -qE '^TOCKB_ADMIN_TOKEN=.+' .env; then
    log "WARNING: TOCKB_ADMIN_TOKEN is empty -- admin routes (/audit, /alias) are public."
    log "  Set it in .env and re-run 'make restart' before production."
fi

# --- Start services ----------------------------------------------------------
log "Building and starting services (this can take a few minutes on first run)..."
docker compose up -d --build

log "Waiting for API to become healthy..."
for i in $(seq 1 60); do
    if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
        log "API is healthy."
        break
    fi
    [[ "$i" -eq 60 ]] && die "API failed to become healthy within 5 minutes"
    sleep 5
done

# --- Migrations (API container runs them, but do it explicitly) --------------
log "Applying migrations..."
docker compose exec -T api alembic upgrade head

# --- Seed root ---------------------------------------------------------------
log "Seeding root node..."
ROOT_ID="$(docker compose exec -T api python -c "
import asyncio
from src.db.session import _init
from src.db.models import ToCNode

async def main():
    factory = _init()
    async with factory() as session:
        root = ToCNode(title='Knowledge Root', depth=0,
                       semantic_summary='Root of the knowledge base')
        session.add(root)
        await session.commit()
        print(root.id)

asyncio.run(main())
" | tr -d '\r\n')"

log ""
log "Ready."
log "   API:      http://localhost:8000/docs"
log "   Console:  http://localhost:3000"
log "   Root ID:  ${ROOT_ID}"
log ""
log "Paste the Root ID into the console to begin ingesting."
