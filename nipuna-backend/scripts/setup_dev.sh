#!/usr/bin/env bash

set -euo pipefail

docker compose up -d postgres redis

echo "Waiting for PostgreSQL to accept connections..."
until docker compose exec -T postgres pg_isready -U postgres -d nipuna_ai >/dev/null 2>&1; do
  sleep 2
done

if [ ! -f .env ]; then
  cp .env.example .env
fi

alembic upgrade head

docker compose up -d api worker
