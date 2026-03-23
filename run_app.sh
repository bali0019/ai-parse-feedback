#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[AI Parse Feedback] Starting..."

export BACKEND_PORT=${PORT:-8000}

echo "[AI Parse Feedback] Starting FastAPI backend on port $BACKEND_PORT"

cd backend
exec python -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT"
