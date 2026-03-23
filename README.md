# AI Parse Feedback

Review and report issues with Databricks `ai_parse_document` results. Upload PDFs, see parsed output with bounding box overlays, click what's wrong, and export structured feedback.

## What It Does

1. **Upload** PDFs (single or multi-file), tagged to a use case
2. **Parse** with `ai_parse_document` v2.0 (runs in background)
3. **Auto-detect** quality issues — flags empty tables, column mismatches, possible checkboxes, reading order anomalies, OCR confusion, and more (orange dashed borders, sorted to top)
4. **Review** page-by-page with color-coded bounding boxes — click any box to mark correct/incorrect with issue category + comment
5. **Export** as ZIP bundle (PDF + page images + annotated issues report) or HTML report — shareable with stakeholders
6. **Import** previously exported bundles to continue review on another instance
7. **Analytics** — issue breakdown by category, filtered by use case

## Quick Start

### Prerequisites

- Databricks CLI v0.278.0+ authenticated to a Databricks workspace
- Node.js 18+ and npm
- Python 3.11+
- psql client (`brew install postgresql@16`)

### Deploy

```bash
# 1. Build frontend
cd frontend && npm install && npm run build && cd ..

# 2. Deploy bundle (creates Lakebase instance, UC Volumes, app)
databricks bundle deploy -t dev

# 3. First-time Lakebase setup (see CLAUDE.md for full commands)
#    - Create database inside the Lakebase instance
#    - Link Unity Catalog
#    - Grant schema permissions to app service principal

# 4. Deploy app code
databricks apps deploy ai-parse-feedback \
  --source-code-path /Workspace/Users/<you>@databricks.com/.bundle/ai-parse-feedback/dev/files \
  --profile $DATABRICKS_PROFILE
```

After deploy, the app URL is shown by:
```bash
databricks apps get ai-parse-feedback --profile $DATABRICKS_PROFILE
```

### Local Dev

```bash
# Backend (terminal 1)
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to the backend.

## Review Workflow

| Action | How |
|--------|-----|
| Navigate pages | Arrow buttons, type page number directly, or `←`/`→` keys |
| Select element | Click bounding box on image or element in list, or `N`/`P` keys |
| Mark correct | Click "Correct" button or press `C` (auto-advances to next) |
| Mark incorrect | Click "Incorrect", pick issue category, add comment, submit |
| Mark page correct | "Mark N correct" button in element list header |
| Mark all correct | "Mark All Correct" button in top bar (entire document) |
| Export ZIP | "Export ZIP" button in top bar |
| Export report | "Report" button — opens HTML with annotated page images per issue |
| Bulk export | Select documents on list page → "Export N selected" or "Report" |
| Import ZIP | "Import ZIP" button on documents page — re-imports exported bundles |

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -v   # 40 tests
cd frontend && npx vitest run                          # 16 tests
```

## Tech Stack

**Frontend:** React + TypeScript + Vite + TailwindCSS
**Backend:** FastAPI + Python
**Database:** Lakebase (Databricks managed Postgres)
**Storage:** UC Volumes
**Parsing:** ai_parse_document v2.0 via SQL Warehouse
**Deployment:** Databricks Asset Bundle (DAB)
