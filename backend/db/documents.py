"""Document CRUD operations for Lakebase."""

import json
import logging
from typing import Optional
from uuid import UUID

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def insert_document(filename: str, volume_path: str, uploaded_by: str = None, use_case_name: str = None) -> str:
    """Insert a new document record. Returns document_id."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (filename, volume_path, uploaded_by, use_case_name, status)
            VALUES (%s, %s, %s, %s, 'uploaded')
            RETURNING document_id
            """,
            (filename, volume_path, uploaded_by, use_case_name),
        )
        row = cur.fetchone()
        doc_id = str(row["document_id"])
        logger.info(f"Inserted document: {doc_id} ({filename})")
        return doc_id


def update_document_status(
    document_id: str,
    status: str,
    error_message: str = None,
    parsed_result: dict = None,
    image_output_path: str = None,
    page_count: int = None,
    element_count: int = None,
    quality_flags: list = None,
):
    """Update document status and optional fields."""
    sets = ["status = %s", "updated_at = now()"]
    params = [status]

    if error_message is not None:
        sets.append("error_message = %s")
        params.append(error_message)
    if parsed_result is not None:
        sets.append("parsed_result = %s::jsonb")
        params.append(json.dumps(parsed_result))
    if image_output_path is not None:
        sets.append("image_output_path = %s")
        params.append(image_output_path)
    if page_count is not None:
        sets.append("page_count = %s")
        params.append(page_count)
    if element_count is not None:
        sets.append("element_count = %s")
        params.append(element_count)
    if quality_flags is not None:
        sets.append("quality_flags = %s::jsonb")
        params.append(json.dumps(quality_flags))
    if status == "parsed":
        sets.append("parsed_at = now()")

    params.append(document_id)

    with get_cursor() as cur:
        cur.execute(
            f"UPDATE documents SET {', '.join(sets)} WHERE document_id = %s",
            params,
        )
    logger.info(f"Updated document {document_id} → {status}")


def get_document(document_id: str) -> Optional[dict]:
    """Get a single document by ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM documents WHERE document_id = %s", (document_id,))
        row = cur.fetchone()
        if row:
            return _serialize_row(row)
        return None


def list_documents(limit: int = 100) -> list[dict]:
    """List all documents ordered by upload time."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM documents ORDER BY uploaded_at DESC LIMIT %s", (limit,)
        )
        return [_serialize_row(r) for r in cur.fetchall()]


def delete_document(document_id: str):
    """Delete a document and its feedback (cascade)."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM documents WHERE document_id = %s", (document_id,))
    logger.info(f"Deleted document {document_id}")


def get_document_feedback_stats(document_id: str) -> dict:
    """Get feedback statistics for a document."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total_feedback,
                COUNT(*) FILTER (WHERE is_correct = true) as correct_count,
                COUNT(*) FILTER (WHERE is_correct = false) as issue_count
            FROM feedback
            WHERE document_id = %s
            """,
            (document_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else {"total_feedback": 0, "correct_count": 0, "issue_count": 0}


def list_use_cases() -> list[dict]:
    """List distinct use cases with doc counts and issue stats."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                COALESCE(d.use_case_name, 'Unassigned') as use_case_name,
                COUNT(DISTINCT d.document_id) as doc_count,
                COALESCE(SUM(d.element_count), 0) as total_elements,
                COUNT(DISTINCT f_all.feedback_id) as total_feedback,
                COUNT(DISTINCT f_issues.feedback_id) as total_issues
            FROM documents d
            LEFT JOIN feedback f_all ON d.document_id = f_all.document_id
            LEFT JOIN feedback f_issues ON d.document_id = f_issues.document_id AND f_issues.is_correct = false
            GROUP BY COALESCE(d.use_case_name, 'Unassigned')
            ORDER BY doc_count DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def list_documents_by_use_case(use_case_name: str, limit: int = 100) -> list[dict]:
    """List documents for a specific use case."""
    with get_cursor() as cur:
        if use_case_name == "Unassigned":
            cur.execute(
                "SELECT * FROM documents WHERE use_case_name IS NULL ORDER BY uploaded_at DESC LIMIT %s",
                (limit,),
            )
        else:
            cur.execute(
                "SELECT * FROM documents WHERE use_case_name = %s ORDER BY uploaded_at DESC LIMIT %s",
                (use_case_name, limit),
            )
        return [_serialize_row(r) for r in cur.fetchall()]


def _serialize_row(row: dict) -> dict:
    """Convert psycopg2 row to JSON-serializable dict."""
    result = {}
    for key, value in row.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result
