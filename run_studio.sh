#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8001}"
HOST="${HOST:-127.0.0.1}"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt

if [ ! -d "frontend/node_modules" ]; then
  (cd frontend && npm install)
fi

(cd frontend && npm run build)

export CRUCIBLE_SANDBOX="${CRUCIBLE_SANDBOX:-local}"
echo "Crucible Studio -> http://${HOST}:${PORT}"
exec .venv/bin/python -m uvicorn crucible.ui.server:app --host "${HOST}" --port "${PORT}" --loop asyncio --http h11
