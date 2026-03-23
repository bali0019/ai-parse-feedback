"""Shared fixtures for backend tests."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


# --- Sample data ---

SAMPLE_DOC_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SAMPLE_FEEDBACK_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def sample_parsed_result():
    """Realistic ai_parse_document v2.0 output."""
    return {
        "document": {
            "pages": [
                {"id": 0, "page_number": 1, "image_uri": "/Volumes/main/default/imgs/page_0.png"},
                {"id": 1, "page_number": 2, "image_uri": "/Volumes/main/default/imgs/page_1.png"},
            ],
            "elements": [
                {
                    "id": 0, "type": "section_header", "content": "Invoice",
                    "bbox": [{"page_id": 0, "coord": [50, 30, 200, 60]}],
                },
                {
                    "id": 1, "type": "text", "content": "Date: 2026-01-15",
                    "bbox": [{"page_id": 0, "coord": [50, 70, 300, 90]}],
                },
                {
                    "id": 2, "type": "table", "content": "<table><tr><td>Item</td><td>Price</td></tr></table>",
                    "bbox": [{"page_id": 0, "coord": [50, 100, 500, 300]}],
                },
                {
                    "id": 3, "type": "text", "content": "Page 2 content",
                    "bbox": [{"page_id": 1, "coord": [50, 50, 400, 80]}],
                },
            ],
        },
        "metadata": {"version": "2.0"},
    }


@pytest.fixture
def sample_document(sample_parsed_result):
    """A document row dict as returned by the DB."""
    return {
        "document_id": UUID(SAMPLE_DOC_ID),
        "filename": "invoice.pdf",
        "volume_path": "/Volumes/main/default/source/invoice.pdf",
        "image_output_path": f"/Volumes/main/default/imgs/{SAMPLE_DOC_ID}/",
        "parsed_result": sample_parsed_result,
        "page_count": 2,
        "element_count": 4,
        "status": "parsed",
        "error_message": None,
        "uploaded_by": None,
        "uploaded_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "parsed_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
    }


@pytest.fixture
def sample_feedback():
    """A feedback row dict as returned by the DB."""
    return {
        "feedback_id": UUID(SAMPLE_FEEDBACK_ID),
        "document_id": UUID(SAMPLE_DOC_ID),
        "element_id": 2,
        "page_id": 0,
        "element_type": "table",
        "bbox_coords": [50, 100, 500, 300],
        "is_correct": False,
        "issue_category": "table_structure_error",
        "comment": "Columns merged",
        "suggested_content": None,
        "suggested_type": None,
        "reviewer": None,
        "created_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
    }


# --- Mock cursor fixture ---

@pytest.fixture
def mock_cursor():
    """Patches get_cursor everywhere it's imported."""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    # Patch at every import site
    with patch("db.documents.get_cursor", return_value=cursor), \
         patch("db.feedback.get_cursor", return_value=cursor), \
         patch("db.connection.get_cursor", return_value=cursor):
        yield cursor


@pytest.fixture
def mock_connection():
    """Patches get_connection everywhere it's imported."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch("db.documents.get_connection", return_value=conn), \
         patch("db.feedback.get_connection", return_value=conn), \
         patch("db.connection.get_connection", return_value=conn):
        yield conn


# --- FastAPI TestClient ---

@pytest.fixture
def client(mock_cursor, sample_document, sample_feedback):
    """FastAPI TestClient with all external deps mocked."""
    with patch("db.migrations.run_migrations"):
        with patch("services.ingest.get_databricks_token", return_value="mock-token"):
            with patch("services.ingest.get_workspace_url", return_value="https://mock.databricks.com"):
                with patch("services.image_loader.get_databricks_token", return_value="mock-token"):
                    with patch("services.image_loader.get_workspace_url", return_value="https://mock.databricks.com"):
                        from main import app
                        yield TestClient(app)
