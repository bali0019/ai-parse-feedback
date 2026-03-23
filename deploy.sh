#!/usr/bin/env bash
# Deploy script — loads your local .env and deploys to Databricks
# Usage: ./deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load local config if .env exists
if [ -f .env ]; then
    source .env
    echo "Loaded config from .env"
fi

# Build frontend
echo "Building frontend..."
cd frontend && npm run build && cd ..

# Deploy bundle with overrides from .env
echo "Deploying bundle..."
databricks bundle deploy -t dev \
    --var="catalog=${CATALOG:-my_catalog}" \
    --var="schema=${SCHEMA:-default}" \
    --var="sql_warehouse_id=${SQL_WAREHOUSE_ID:-}" \
    --profile "${DATABRICKS_PROFILE:-DEFAULT}"

# Deploy app code
echo "Deploying app code..."
WORKSPACE_USER=$(databricks current-user me --profile "${DATABRICKS_PROFILE:-DEFAULT}" -o json | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])")
databricks apps deploy ai-parse-feedback \
    --source-code-path "/Workspace/Users/${WORKSPACE_USER}/.bundle/ai-parse-feedback/dev/files" \
    --profile "${DATABRICKS_PROFILE:-DEFAULT}"

echo "Done! Check app status:"
echo "  databricks apps get ai-parse-feedback --profile ${DATABRICKS_PROFILE:-DEFAULT}"
