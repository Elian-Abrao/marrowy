#!/usr/bin/env bash
set -euo pipefail

docker compose up -d postgres
source .venv/bin/activate
alembic upgrade head
marrowy seed
marrowy serve
