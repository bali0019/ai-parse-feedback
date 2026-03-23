"""Run ai_query on a cropped element region from a page image."""

import io
import json
import time
import uuid
import logging

import requests
from PIL import Image
from databricks.sdk import WorkspaceClient

from config import SQL_WAREHOUSE_ID, IMAGE_OUTPUT_VOLUME_PATH
from utils.auth import get_databricks_token, get_workspace_url

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS = {
    "table": "Extract the table structure with all rows and columns from this image. Return as markdown table.",
    "text": "Extract all text content from this image region exactly as it appears.",
    "figure": "Describe what is shown in this image region in detail.",
    "section_header": "Extract the heading/title text from this image region.",
    "list": "Extract all list items from this image region.",
    "caption": "Extract the caption text from this image region.",
}


def get_default_prompt(element_type: str) -> str:
    """Return a sensible default prompt for a given element type."""
    return DEFAULT_PROMPTS.get(element_type, "What content is in this image region? Extract it accurately.")


def crop_and_query(
    image_uri: str,
    bbox_coord: list,
    prompt: str,
    element_type: str = "",
    current_content: str = "",
) -> dict:
    """
    Crop a bounding box region from a page image and run ai_query.

    1. Download the page image from UC Volume
    2. Crop to bbox region using PIL
    3. Upload cropped image to temp UC Volume path
    4. Run ai_query via Statement Execution API
    5. Return result
    """
    if not SQL_WAREHOUSE_ID:
        raise Exception("SQL_WAREHOUSE_ID not configured")

    token = get_databricks_token()
    workspace_url = get_workspace_url()

    # 1. Download page image
    api_url = f"{workspace_url}/api/2.0/fs/files{image_uri}"
    resp = requests.get(api_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    resp.raise_for_status()
    img_bytes = resp.content

    # 2. Crop to bbox
    img = Image.open(io.BytesIO(img_bytes))
    x1, y1, x2, y2 = bbox_coord
    # Clamp to image bounds
    x1 = max(0, int(x1))
    y1 = max(0, int(y1))
    x2 = min(img.width, int(x2))
    y2 = min(img.height, int(y2))

    # Add small padding (5% of bbox size) for context
    pad_x = int((x2 - x1) * 0.05)
    pad_y = int((y2 - y1) * 0.05)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(img.width, x2 + pad_x)
    y2 = min(img.height, y2 + pad_y)

    cropped = img.crop((x1, y1, x2, y2))

    # 3. Upload cropped image to temp path
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    cropped_bytes = buf.getvalue()

    temp_filename = f"crop_{uuid.uuid4().hex[:12]}.png"
    temp_path = f"{IMAGE_OUTPUT_VOLUME_PATH}/_ai_query/{temp_filename}"

    upload_url = f"{workspace_url}/api/2.0/fs/files{temp_path}"
    upload_resp = requests.put(
        upload_url,
        data=cropped_bytes,
        headers={"Authorization": f"Bearer {token}"},
        params={"overwrite": "true"},
    )
    if upload_resp.status_code not in (200, 201, 204):
        raise Exception(f"Failed to upload cropped image: {upload_resp.status_code} {upload_resp.text}")

    logger.info(f"Uploaded cropped image to {temp_path} ({len(cropped_bytes)} bytes, {x2-x1}x{y2-y1}px)")

    # 4. Parse catalog/schema from volume path
    parts = IMAGE_OUTPUT_VOLUME_PATH.strip("/").split("/")
    if len(parts) < 4 or parts[0] != "Volumes":
        raise Exception(f"Invalid IMAGE_OUTPUT_VOLUME_PATH: {IMAGE_OUTPUT_VOLUME_PATH}")
    catalog, schema = parts[1], parts[2]

    # Build prompt with context
    full_prompt = prompt
    if current_content:
        full_prompt += f"\n\nFor reference, the current parsed content is:\n{current_content[:500]}"

    # Escape single quotes in prompt for SQL
    safe_prompt = full_prompt.replace("'", "''")

    sql_query = f"""
    SELECT ai_query(
        'databricks-meta-llama-3-3-70b-instruct',
        '{safe_prompt}',
        image => read_files('{temp_path}')
    ) AS result
    """

    logger.info(f"Running ai_query on {temp_path}")

    w = WorkspaceClient()
    stmt = w.statement_execution.execute_statement(
        statement=sql_query,
        warehouse_id=SQL_WAREHOUSE_ID,
        catalog=catalog,
        schema=schema,
    )

    # Poll until complete (shorter timeout for single region)
    max_wait = 120
    start = time.time()
    while stmt.status.state.value in ("PENDING", "RUNNING"):
        if time.time() - start > max_wait:
            raise Exception(f"ai_query timeout after {max_wait}s")
        time.sleep(2)
        stmt = w.statement_execution.get_statement(stmt.statement_id)

    if stmt.status.state.value == "FAILED":
        error_msg = stmt.status.error.message if stmt.status.error else "Unknown error"
        raise Exception(f"ai_query failed: {error_msg}")

    if not stmt.result or not stmt.result.data_array:
        raise Exception("No data returned from ai_query")

    result_text = stmt.result.data_array[0][0] or ""

    # Clean up temp file (best effort)
    try:
        requests.delete(
            f"{workspace_url}/api/2.0/fs/files{temp_path}",
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        pass

    logger.info(f"ai_query result: {len(result_text)} chars")

    return {
        "result": result_text,
        "model": "databricks-meta-llama-3-3-70b-instruct",
        "crop_size": f"{x2-x1}x{y2-y1}",
    }
