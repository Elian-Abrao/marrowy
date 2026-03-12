#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp -n .env.example .env || true
playwright install chromium >/dev/null 2>&1 || true
echo "Bootstrap complete."
