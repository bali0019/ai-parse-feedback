"""Feedback CRUD operations for Lakebase (with upsert)."""

import json
import logging
from typing import Optional
from uuid import UUID

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def upsert_feedback(
    document_id: str,
    element_id: int,
    page_id: int,
    element_type: str = None,
    bbox_coords: list = None,
    is_correct: bool = None,
    issue_category: str = None,
    comment: str = None,
    suggested_content: str = None,
    suggested_type: str = None,
    reviewer: str = None,
) -> str:
    """Insert or update feedback for a document element. Returns feedback_id."""
    bbox_json = json.dumps(bbox_coords) if bbox_coords else None

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO feedback (
                document_id, element_id, page_id, element_type, bbox_coords,
                is_correct, issue_category, comment, suggested_content,
                suggested_type, reviewer
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, element_id)
            DO UPDATE SET
                page_id = EXCLUDED.page_id,
                element_type = EXCLUDED.element_type,
                bbox_coords = EXCLUDED.bbox_coords,
                is_correct = EXCLUDED.is_correct,
                issue_category = EXCLUDED.issue_category,
                comment = EXCLUDED.comment,
                suggested_content = EXCLUDED.suggested_content,
                suggested_type = EXCLUDED.suggested_type,
                reviewer = EXCLUDED.reviewer,
                updated_at = now()
            RETURNING feedback_id
            """,
            (
                document_id, element_id, page_id, element_type, bbox_json,
                is_correct, issue_category, comment, suggested_content,
                suggested_type, reviewer,
            ),
        )
        row = cur.fetchone()
        feedback_id = str(row["feedback_id"])
        logger.info(f"Upserted feedback {feedback_id} for doc={document_id} element={element_id}")
        return feedback_id


def get_feedback_for_document(document_id: str) -> list[dict]:
    """Get all feedback for a document."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM feedback
            WHERE document_id = %s
            ORDER BY page_id, element_id
            """,
            (document_id,),
        )
        return [_serialize_row(r) for r in cur.fetchall()]


def get_feedback_for_page(document_id: str, page_id: int) -> list[dict]:
    """Get feedback for a specific page of a document."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM feedback
            WHERE document_id = %s AND page_id = %s
            ORDER BY element_id
            """,
            (document_id, page_id),
        )
        return [_serialize_row(r) for r in cur.fetchall()]


def bulk_upsert_feedback(document_id: str, items: list[dict]) -> int:
    """Insert or update feedback for many elements in a single transaction. Returns count."""
    if not items:
        return 0

    with get_cursor() as cur:
        # Use executemany with a single connection for all items
        sql = """
            INSERT INTO feedback (
                document_id, element_id, page_id, element_type, bbox_coords,
                is_correct, issue_category, comment
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (document_id, element_id)
            DO UPDATE SET
                page_id = EXCLUDED.page_id,
                element_type = EXCLUDED.element_type,
                bbox_coords = EXCLUDED.bbox_coords,
                is_correct = EXCLUDED.is_correct,
                issue_category = EXCLUDED.issue_category,
                comment = EXCLUDED.comment,
                updated_at = now()
        """
        params = [
            (
                document_id,
                item.get("element_id"),
                item.get("page_id"),
                item.get("element_type"),
                json.dumps(item["bbox_coords"]) if item.get("bbox_coords") else None,
                item.get("is_correct"),
                item.get("issue_category"),
                item.get("comment"),
            )
            for item in items
        ]
        cur.executemany(sql, params)
        logger.info(f"Bulk upserted {len(items)} feedback items for doc={document_id}")
        return len(items)


def delete_feedback(feedback_id: str):
    """Delete a single feedback entry."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM feedback WHERE feedback_id = %s", (feedback_id,))
    logger.info(f"Deleted feedback {feedback_id}")


def _serialize_row(row: dict) -> dict:
    result = {}
    for key, value in row.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result
