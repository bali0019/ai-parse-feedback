"""Configuration for AI Parse Feedback app."""

import os

# Databricks workspace
DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "")
if DATABRICKS_HOST and not DATABRICKS_HOST.startswith(("http://", "https://")):
    DATABRICKS_HOST = f"https://{DATABRICKS_HOST}"

# SQL Warehouse for ai_parse_document execution
SQL_WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "")

# UC Volume paths
VOLUME_PATH = os.environ.get("VOLUME_PATH", "/Volumes/main/default/parse_feedback_source")
IMAGE_OUTPUT_VOLUME_PATH = os.environ.get("IMAGE_OUTPUT_VOLUME_PATH", "/Volumes/main/default/parse_feedback_images")

# Lakebase (Postgres) connection — PG* env vars auto-injected by Databricks Apps
# when a database resource is defined in databricks.yml
PGHOST = os.environ.get("PGHOST", "")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGUSER = os.environ.get("PGUSER", "")
PGDATABASE = os.environ.get("PGDATABASE", "ai_parse_feedback")
PGSSLMODE = os.environ.get("PGSSLMODE", "require")

# Volume config helper
def parse_volume_path(volume_path: str) -> dict | None:
    try:
        parts = volume_path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "Volumes":
            return {
                "catalog": parts[1],
                "schema": parts[2],
                "volume_name": parts[3],
                "full_path": volume_path,
            }
    except Exception:
        pass
    return None

VOLUME_CONFIG = parse_volume_path(VOLUME_PATH)

# Issue categories for feedback
ISSUE_CATEGORIES = [
    {"value": "wrong_element_type", "label": "Wrong Element Type", "description": "Element classified as wrong type (e.g., table as figure)"},
    {"value": "incorrect_boundaries", "label": "Incorrect Boundaries", "description": "Bounding box doesn't match actual content region"},
    {"value": "missing_content", "label": "Missing Content", "description": "Element content is empty or incomplete"},
    {"value": "merged_elements", "label": "Merged Elements", "description": "Separate elements incorrectly merged into one"},
    {"value": "split_elements", "label": "Split Elements", "description": "One element incorrectly split into multiple"},
    {"value": "duplicate_content", "label": "Duplicate Content", "description": "Same content appears in multiple elements"},
    {"value": "ocr_error", "label": "OCR Error", "description": "Characters misread by OCR"},
    {"value": "table_structure_error", "label": "Table Structure Error", "description": "Table HTML malformed, missing columns, or excessive empty cells"},
    {"value": "checkbox_not_recognized", "label": "Checkbox Not Recognized", "description": "Checkbox detected as empty text, state not captured"},
    {"value": "chart_data_not_extracted", "label": "Chart Data Not Extracted", "description": "Chart recognized as figure but data values not extracted"},
    {"value": "generic_image_placeholder", "label": "Generic Image Placeholder", "description": "Image references use generic placeholder filenames"},
    {"value": "content_truncated", "label": "Content Truncated", "description": "Content cut off or incomplete"},
    {"value": "wrong_reading_order", "label": "Wrong Reading Order", "description": "Elements in wrong sequence"},
    {"value": "header_footer_misclassified", "label": "Header/Footer Misclassified", "description": "Section titles classified as page headers/footers or vice versa"},
    {"value": "other", "label": "Other", "description": "Other issue not in predefined categories"},
]

# Element type colors
ELEMENT_COLORS = {
    "section_header": "#FF6B6B",
    "text": "#4ECDC4",
    "figure": "#45B7D1",
    "caption": "#96CEB4",
    "page_footer": "#FFEAA7",
    "page_header": "#DDA0DD",
    "table": "#98D8C8",
    "list": "#F7DC6F",
    "default": "#BDC3C7",
}

# Export/import job
EXPORT_JOB_ID = os.environ.get("EXPORT_JOB_ID")
EXPORT_JOB_PAGE_THRESHOLD = 50  # If total pages > this, use serverless job
IMPORT_SIZE_THRESHOLD_MB = 10   # If ZIP > this MB, use serverless job

MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "100"))
SUPPORTED_FILE_TYPES = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"]
