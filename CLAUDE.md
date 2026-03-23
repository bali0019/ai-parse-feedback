# AI Parse Feedback

Human-in-the-loop review app for Databricks `ai_parse_document` results. Upload PDFs, view parsed output with color-coded bounding box overlays page-by-page, click elements to submit structured feedback, export as ZIP bundles or HTML reports with annotated page images.

## Architecture

- **Frontend:** React 18 + TypeScript + Vite + TailwindCSS
- **Backend:** FastAPI + Python (uvicorn)
- **Database:** Lakebase (Databricks managed Postgres) — PG* env vars auto-injected, OAuth token auth via REST API
- **Storage:** UC Volumes for source documents and page images
- **Parsing:** `ai_parse_document` v2.0 via SQL Warehouse (Statement Execution API)
- **Deployment:** Databricks Asset Bundle (DAB)

## Project Structure

```
ai_parse_feedback_app/
├── databricks.yml                   # DAB bundle (resources, variables, targets)
├── app.yaml                         # Databricks App config (command + env vars)
├── run_app.sh                       # Startup script (unused — app.yaml runs uvicorn directly)
├── requirements.txt                 # Root requirements (pip installed by Databricks Apps runtime)
│
├── backend/
│   ├── main.py                      # FastAPI app: CORS, migrations, static serving, routers
│   ├── config.py                    # Env vars, 15 issue categories, 8 element colors
│   ├── requirements.txt             # Backend-specific requirements
│   ├── pytest.ini
│   ├── api/
│   │   ├── documents.py             # /api/documents/* — upload, parse, list, get, page data, delete
│   │   ├── feedback.py              # /api/feedback/* — upsert, bulk, list, delete
│   │   └── export.py                # /api/export/* — ZIP, HTML report, bulk report, import
│   ├── db/
│   │   ├── connection.py            # Lakebase OAuth connection (REST API credential gen)
│   │   ├── migrations.py            # Auto-create tables on startup
│   │   ├── documents.py             # Document CRUD
│   │   └── feedback.py              # Feedback CRUD with upsert (ON CONFLICT)
│   ├── services/
│   │   ├── ingest.py                # Upload to UC Volume via Files API
│   │   ├── parse.py                 # ai_parse_document via SQL Warehouse (10 min timeout)
│   │   ├── image_loader.py          # Fetch page images from UC Volume as base64
│   │   └── quality_checks.py        # Auto-detect quality issues (7 heuristic checks)
│   ├── utils/
│   │   └── auth.py                  # OAuth token (Apps mode + local CLI fallback)
│   └── tests/                       # 40 pytest tests (config, services, db, api, export)
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts               # TailwindCSS, /api proxy to :8000, @ path alias
│   ├── vitest.config.ts             # 16 vitest tests
│   └── src/
│       ├── main.tsx                 # React entry: QueryClient + BrowserRouter
│       ├── App.tsx                  # Nav + Routes (/, /upload, /documents, /review/:id)
│       ├── lib/
│       │   ├── types.ts             # TypeScript interfaces
│       │   └── api.ts               # Typed fetch wrappers for all endpoints
│       ├── components/
│       │   ├── PageAnnotator.tsx     # Page image with clickable color-coded bbox overlays
│       │   └── FeedbackForm.tsx      # Correct/incorrect + category + comment + auto-advance
│       └── pages/
│           ├── HomePage.tsx          # Use case list with doc counts + issue stats
│           ├── UploadPage.tsx        # Multi-file drag-drop upload + use case name + parse trigger
│           ├── DocumentsPage.tsx     # Document list with checkboxes, bulk export/report/delete, import
│           └── ReviewPage.tsx        # Split pane: annotator + element list + feedback + quality flags
```

## Features

- **Use-case-scoped views** — home page groups documents by use case with issue stats; upload tags docs to a use case
- **Multi-file upload** with progress tracking per file and use case name input
- **Background parsing** — returns immediately, frontend polls for completion
- **Auto-detect quality issues** — 7 heuristic checks run after parse, flagging suspicious elements with orange dashed borders (see below)
- **Page-by-page review** with page jump input (type page number directly)
- **Clickable bounding boxes** color-coded by element type
- **Auto-advance** to next unreviewed element after submitting feedback, auto-advances to next page at end
- **"Mark N correct"** button per page for bulk-approving remaining elements
- **"Mark All Correct"** button for entire document via bulk API
- **Keyboard shortcuts**: `C` (correct+next), `N`/`P` (next/prev element), `←`/`→` (prev/next page)
- **ZIP export** — self-contained bundle (PDF + page images + parsed_result.json + manifest.jsonl + issues_report.html)
- **HTML report** — print-friendly page with annotated page images showing bbox overlays for each issue
- **Bulk export/report** — select multiple documents from list page
- **Import** — re-import ZIP bundles (single or bulk) to continue review on another instance

## Auto-Detect Quality Heuristics

After parsing, 7 rule-based checks run automatically on the parsed output and flag suspicious elements. Flagged elements show **orange dashed borders** in the page view and a **⚠ icon** in the element list (sorted to top for review priority).

| Check | What it detects | Severity |
|-------|----------------|----------|
| Empty table cells | Tables with >50% empty `<td>` cells | warning |
| Column count mismatch | Header `<th>` count != data `<td>` count in rows | warning |
| Unclosed HTML tags | `<table>` tags without matching `</table>` | warning |
| Possible checkbox | Small text elements (<30x30px) with empty/single-char content | info |
| Reading order anomaly | Sequential elements where Y-coordinate jumps backwards >200px on same page | info |
| Mixed Unicode scripts | Content with 3+ distinct Unicode script ranges (e.g., Latin + CJK) | info |
| Suspicious numeric OCR | Letter `O` appearing in otherwise numeric strings (likely `0`) | warning |

Quality flags are stored in `quality_flags JSONB` on the documents table and included in the page data API response. They do NOT modify the parsed_result — the original ai_parse_document output is preserved unchanged.

## Application Flow

```
1. Upload    → POST /api/documents/upload       → Files API → UC Volume → Lakebase (status: uploaded)
2. Parse     → POST /api/documents/{id}/parse   → BackgroundTask → SQL Warehouse ai_parse_document() → Lakebase (status: parsed)
3. Review    → GET  /api/documents/{id}/page/N   → page image (base64) + elements + existing feedback
4. Feedback  → POST /api/feedback                → Lakebase upsert (ON CONFLICT document_id, element_id)
5. Bulk FB   → POST /api/feedback/bulk           → batch upsert for mark-all-correct
6. Export    → GET  /api/export/document/{id}     → ZIP bundle
7. Report    → GET  /api/export/report/{id}       → HTML with annotated page images per issue
8. Bulk Exp  → POST /api/export/bulk              → ZIP with all selected docs
9. Bulk Rpt  → POST /api/export/bulk-report       → combined HTML report
10. Import   → POST /api/export/import            → unzip → Lakebase records
```

## Database Schema

**documents** — One row per uploaded document
- `document_id` UUID PK, `filename`, `volume_path`, `image_output_path`
- `parsed_result` JSONB (full ai_parse_document v2.0 output), `page_count`, `element_count`
- `status` (uploaded → parsing → parsed → failed), `error_message`
- `uploaded_at`, `parsed_at`, `updated_at` TIMESTAMPTZ

**feedback** — One row per reviewed element (unique on document_id + element_id)
- `feedback_id` UUID PK, `document_id` FK (cascade), `element_id`, `page_id`
- `element_type`, `bbox_coords` JSONB, `is_correct` BOOLEAN
- `issue_category`, `comment`, `suggested_content`, `suggested_type`, `reviewer`

## DAB Bundle Resources

| Resource | Type | Permission |
|----------|------|------------|
| source-volume | UC Volume (MANAGED) `parse_feedback_source` | WRITE_VOLUME |
| image-output-volume | UC Volume (MANAGED) `parse_feedback_images` | WRITE_VOLUME |
| parse-warehouse | SQL Warehouse | CAN_USE |
| database | Lakebase `ai-parse-feedback-db` (DAB-created instance) | CAN_CONNECT_AND_CREATE |

**Variables:** catalog, schema, sql_warehouse_id, database_instance_name, database_name
**Target:** `dev` (configured via `.env` — see `.env.example`)

## Deploy Workflow (Step by Step)

### 1. Build frontend

```bash
cd frontend
npm install
npm run build    # outputs to frontend/dist/
cd ..
```

`frontend/dist/` is included in the DAB sync (`.gitignore` has `dist` removed). `node_modules/` and `frontend/src/` are excluded.

### 2. Validate and deploy bundle

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

This creates:
- Lakebase instance `ai-parse-feedback-db` (CU_1)
- UC Volumes `parse_feedback_source` + `parse_feedback_images`
- Databricks App `ai-parse-feedback` with all resource permissions

### 3. First-time Lakebase setup (only once)

After the first `databricks bundle deploy`, three manual steps are required:

**Step 3a: Create database inside the Lakebase instance**

```bash
PROFILE=$DATABRICKS_PROFILE
INSTANCE=ai-parse-feedback-db

HOST=$(databricks database get-database-instance $INSTANCE -p $PROFILE -o json | python3 -c "import sys,json; print(json.load(sys.stdin)['read_write_dns'])")
TOKEN=$(databricks database generate-database-credential --json "{\"instance_names\": [\"$INSTANCE\"], \"request_id\": \"setup-1\"}" -p $PROFILE -o json | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
EMAIL=$(databricks current-user me -p $PROFILE -o json | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])")

PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=postgres user=$EMAIL sslmode=require" \
  -c "CREATE DATABASE \"ai-parse-feedback-db\";"
```

**Step 3b: Link Unity Catalog**

```bash
databricks database create-database-catalog ai_parse_feedback ai-parse-feedback-db ai-parse-feedback-db -p $PROFILE
```

**Step 3c: Grant schema permissions to app service principal**

Get the SP UUID from `databricks apps get ai-parse-feedback -p $PROFILE` → `service_principal_client_id`:

```bash
SP_UUID="<service_principal_client_id>"

PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=ai-parse-feedback-db user=$EMAIL sslmode=require" -c "
GRANT ALL ON SCHEMA public TO \"$SP_UUID\";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO \"$SP_UUID\";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO \"$SP_UUID\";
"
```

### 4. Deploy app code

```bash
databricks apps deploy ai-parse-feedback \
  --source-code-path /Workspace/Users/<you>@databricks.com/.bundle/ai-parse-feedback/dev/files \
  --profile $DATABRICKS_PROFILE
```

### 5. Verify

```bash
databricks apps get ai-parse-feedback --profile $DATABRICKS_PROFILE
# Should show: app_status.state = RUNNING
# URL: https://ai-parse-feedback-<id>.aws.databricksapps.com
```

### Subsequent deploys (after first-time setup)

```bash
cd frontend && npm run build && cd ..
databricks bundle deploy -t dev
databricks apps deploy ai-parse-feedback \
  --source-code-path /Workspace/Users/<you>@databricks.com/.bundle/ai-parse-feedback/dev/files \
  --profile $DATABRICKS_PROFILE
```

That's it — no Lakebase steps needed after the first deploy.

## Running Tests

```bash
# Backend (40 tests)
cd backend
.venv/bin/python -m pytest tests/ -v

# Frontend (16 tests)
cd frontend
npx vitest run
```

## Local Development

```bash
# Backend (terminal 1)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABRICKS_CONFIG_PROFILE=$DATABRICKS_PROFILE
uvicorn main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev   # localhost:5173, proxies /api → :8000
```

## Lakebase Connection Details

The app connects to Lakebase using OAuth tokens via the REST API:
- `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGSSLMODE` — auto-injected by Databricks Apps when `database` resource is defined in `databricks.yml`
- `LAKEBASE_INSTANCE_NAME` — set in `app.yaml`, used by `db/connection.py` to call `POST /api/2.0/database/credentials` with `request_id` for token generation
- No password stored — fresh OAuth token per connection

## ai_parse_document v2.0 Output Format

- `document.pages[]` — `{id, page_number, image_uri}`
- `document.elements[]` — `{id, type, content, description, bbox[]}`
- Each bbox: `{page_id: int, coord: [x1, y1, x2, y2]}` (pixel coordinates, element-level)
- Element types: text, table, figure, section_header, caption, page_header, page_footer, list

## Issue Categories (15)

wrong_element_type, incorrect_boundaries, missing_content, merged_elements, split_elements, duplicate_content, ocr_error, table_structure_error, checkbox_not_recognized, chart_data_not_extracted, generic_image_placeholder, content_truncated, wrong_reading_order, header_footer_misclassified, other

## Element Type Colors

| Type | Hex |
|------|-----|
| section_header | #FF6B6B |
| text | #4ECDC4 |
| figure | #45B7D1 |
| caption | #96CEB4 |
| page_footer | #FFEAA7 |
| page_header | #DDA0DD |
| table | #98D8C8 |
| list | #F7DC6F |

## Export Formats

**ZIP Bundle** — self-contained, re-importable:
```
{filename}_feedback_{date}.zip
├── manifest.jsonl              # JSONL: metadata → element* (with feedback) → summary
├── source/{filename}           # Original PDF
├── pages/page_0.png ...        # Page images
└── parsed_result.json          # Full ai_parse_document output
```

**HTML Report** — print-friendly, includes:
- Summary stats (pages, elements, reviewed, correct, issues)
- Issue breakdown by category
- Per-issue: page image with colored bbox overlay highlighting the problem element + category badge + comment

## Key Design Decisions

- **React over Streamlit** — clickable bbox overlays, resizable split panes, keyboard shortcuts
- **Lakebase over Delta** — JSONB, foreign keys, fast CRUD with upsert, no SQL Warehouse overhead
- **Background parsing** — `POST /parse` returns immediately, frontend polls via React Query
- **Auto-advance** — submit feedback → next unreviewed element → next page when done
- **OAuth per connection** — no stale token issues; `db/connection.py` generates fresh token via REST API for each connection
- **DAB-managed Lakebase instance** — `database_instances` resource in `databricks.yml` creates it on deploy

## Future Backlog

- Multi-user review queue with document assignment
- Import pre-parsed ai_parse_document JSON (skip upload+parse)
- Analytics page with issue distribution charts
- PDF.js in-browser rendering alongside parse output
- Job-based parsing (Databricks Jobs instead of BackgroundTask) for very large documents
