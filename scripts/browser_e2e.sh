#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
playwright install chromium
pytest -q tests/e2e/test_browser_ui.py
