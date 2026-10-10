#!/usr/bin/env bash
# One command: creates the virtual environment on first run, then serves the dashboard at http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Creating the virtual environment (first run only)..."
  (python3.12 -m venv .venv 2>/dev/null || python3.11 -m venv .venv || python3 -m venv .venv)
  .venv/bin/python -m pip install -q -r requirements.txt
fi
[ -f data/cache/runs/N/run.json ] || { echo "Building the cached scenarios..."; .venv/bin/python -m dt.api rebuild; }
if [ ! -f web/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then echo "Building the dashboard..."; (cd web && npm install --no-audit --no-fund && npm run build); else echo "The dashboard build is missing and Node is not installed: only the API will run."; fi
fi
echo "Dashboard: http://localhost:8000"
exec .venv/bin/python -m uvicorn server.app:app --port 8000
