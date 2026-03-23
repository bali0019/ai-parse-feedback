"""Tests for db/documents.py."""

from unittest.mock import patch, MagicMock
from uuid import UUID
from datetime import datetime, timezone

import pytest

from db.documents import (
    insert_document,
    update_document_status,
    get_document,
    list_documents,
    delete_document,
    get_document_feedback_stats,
    _serialize_row,
)


def test_insert_document(mock_cursor):
    mock_cursor.fetchone.return_value = {"document_id": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")}
    result = insert_document("test.pdf", "/Volumes/main/default/vol/test.pdf")
    assert result == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO documents" in sql


def test_update_document_status(mock_cursor):
    update_document_status("some-id", status="parsed", page_count=5)
    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "UPDATE documents SET" in sql
    params = mock_cursor.execute.call_args[0][1]
    assert "parsed" in params
    assert 5 in params


def test_get_document_found(mock_cursor):
    mock_cursor.fetchone.return_value = {
        "document_id": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        "filename": "test.pdf",
        "status": "parsed",
        "uploaded_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    result = get_document("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert result is not None
    assert result["document_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert result["filename"] == "test.pdf"


def test_get_document_not_found(mock_cursor):
    mock_cursor.fetchone.return_value = None
    result = get_document("nonexistent")
    assert result is None


def test_list_documents(mock_cursor):
    mock_cursor.fetchall.return_value = [
        {"document_id": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), "filename": "a.pdf",
         "uploaded_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        {"document_id": UUID("11111111-2222-3333-4444-555555555555"), "filename": "b.pdf",
         "uploaded_at": datetime(2026, 1, 2, tzinfo=timezone.utc)},
    ]
    result = list_documents(limit=10)
    assert len(result) == 2
    assert result[0]["filename"] == "a.pdf"


def test_delete_document(mock_cursor):
    delete_document("some-id")
    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "DELETE FROM documents" in sql


def test_get_feedback_stats(mock_cursor):
    mock_cursor.fetchone.return_value = {"total_feedback": 10, "correct_count": 7, "issue_count": 3}
    result = get_document_feedback_stats("some-id")
    assert result["total_feedback"] == 10
    assert result["issue_count"] == 3


def test_serialize_row():
    row = {
        "id": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "name": "test",
        "count": 42,
    }
    result = _serialize_row(row)
    assert result["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert result["created_at"] == "2026-01-01T00:00:00+00:00"
    assert result["name"] == "test"
    assert result["count"] == 42
