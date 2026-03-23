"""Tests for db/feedback.py."""

from uuid import UUID
from datetime import datetime, timezone

from db.feedback import (
    upsert_feedback,
    get_feedback_for_document,
    get_feedback_for_page,
    delete_feedback,
)


def test_upsert_feedback_insert(mock_cursor):
    mock_cursor.fetchone.return_value = {"feedback_id": UUID("11111111-2222-3333-4444-555555555555")}
    result = upsert_feedback(
        document_id="doc-id",
        element_id=5,
        page_id=0,
        element_type="text",
        is_correct=True,
    )
    assert result == "11111111-2222-3333-4444-555555555555"
    sql = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO feedback" in sql
    assert "ON CONFLICT" in sql


def test_upsert_feedback_with_issue(mock_cursor):
    mock_cursor.fetchone.return_value = {"feedback_id": UUID("11111111-2222-3333-4444-555555555555")}
    result = upsert_feedback(
        document_id="doc-id",
        element_id=5,
        page_id=0,
        is_correct=False,
        issue_category="ocr_error",
        comment="Wrong character",
    )
    assert result == "11111111-2222-3333-4444-555555555555"


def test_get_feedback_for_document(mock_cursor):
    mock_cursor.fetchall.return_value = [
        {"feedback_id": UUID("11111111-2222-3333-4444-555555555555"), "element_id": 1, "page_id": 0,
         "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
         "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ]
    result = get_feedback_for_document("doc-id")
    assert len(result) == 1
    assert result[0]["element_id"] == 1


def test_get_feedback_for_page(mock_cursor):
    mock_cursor.fetchall.return_value = []
    result = get_feedback_for_page("doc-id", 5)
    assert result == []
    sql = mock_cursor.execute.call_args[0][0]
    assert "page_id" in sql


def test_delete_feedback(mock_cursor):
    delete_feedback("fb-id")
    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "DELETE FROM feedback" in sql
