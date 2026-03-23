"""Parse documents using ai_parse_document via SQL Warehouse.

Parse documents using ai_parse_document via SQL Warehouse. Returns full structured JSON output
(not just concatenated text) for bounding box review.
"""

import json
import time
import logging

from databricks.sdk import WorkspaceClient

from config import SQL_WAREHOUSE_ID

logger = logging.getLogger(__name__)


def parse_document(volume_path: str, image_output_path: str) -> dict:
    """
    Run ai_parse_document on a file in UC Volume.

    Returns the full parsed document JSON with pages, elements, and bounding boxes.
    """
    if not SQL_WAREHOUSE_ID:
        raise Exception("SQL_WAREHOUSE_ID not configured")

    # Parse catalog/schema from volume path
    parts = volume_path.strip("/").split("/")
    if len(parts) < 4 or parts[0] != "Volumes":
        raise Exception(f"Invalid volume path: {volume_path}")

    catalog, schema = parts[1], parts[2]

    sql_query = f"""
    WITH parsed_documents AS (
        SELECT
            path,
            ai_parse_document(
                content,
                map(
                    'version', '2.0',
                    'imageOutputPath', '{image_output_path}',
                    'descriptionElementTypes', '*'
                )
            ) AS parsed
        FROM READ_FILES('{volume_path}', format => 'binaryFile')
    )
    SELECT path, parsed
    FROM parsed_documents
    """

    logger.info(f"Parsing {volume_path} via warehouse {SQL_WAREHOUSE_ID}")

    w = WorkspaceClient()
    stmt = w.statement_execution.execute_statement(
        statement=sql_query,
        warehouse_id=SQL_WAREHOUSE_ID,
        catalog=catalog,
        schema=schema,
    )

    # Poll until complete
    max_wait = 600  # 10 minutes for large docs
    start = time.time()
    while stmt.status.state.value in ("PENDING", "RUNNING"):
        if time.time() - start > max_wait:
            raise Exception(f"Parse timeout after {max_wait}s")
        time.sleep(2)
        stmt = w.statement_execution.get_statement(stmt.statement_id)

    if stmt.status.state.value == "FAILED":
        error_msg = stmt.status.error.message if stmt.status.error else "Unknown error"
        raise Exception(f"Parse failed: {error_msg}")

    if not stmt.result or not stmt.result.data_array:
        raise Exception("No data returned from ai_parse_document")

    row = stmt.result.data_array[0]
    parsed_json_str = row[1] if len(row) > 1 else None

    if not parsed_json_str:
        raise Exception("Empty parse result")

    parsed_doc = json.loads(parsed_json_str) if isinstance(parsed_json_str, str) else parsed_json_str

    # Extract summary stats
    document = parsed_doc.get("document", {})
    pages = document.get("pages", [])
    elements = document.get("elements", [])

    logger.info(f"Parsed: {len(pages)} pages, {len(elements)} elements")

    return {
        "parsed_result": parsed_doc,
        "page_count": len(pages),
        "element_count": len(elements),
        "image_output_path": image_output_path,
    }
