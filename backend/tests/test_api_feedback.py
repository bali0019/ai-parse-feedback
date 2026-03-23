"""Tests for API feedback endpoints."""

from unittest.mock import patch
from tests.conftest import SAMPLE_DOC_ID, SAMPLE_FEEDBACK_ID


def test_submit_feedback(client):
    with patch("api.feedback.feedback_db.upsert_feedback", return_value=SAMPLE_FEEDBACK_ID):
        resp = client.post("/api/feedback", json={
            "document_id": SAMPLE_DOC_ID,
            "element_id": 2,
            "page_id": 0,
            "element_type": "table",
            "is_correct": False,
            "issue_category": "table_structure_error",
            "comment": "Merged columns",
        })
        assert resp.status_code == 200
        assert resp.json()["feedback_id"] == SAMPLE_FEEDBACK_ID


def test_submit_feedback_correct(client):
    with patch("api.feedback.feedback_db.upsert_feedback", return_value=SAMPLE_FEEDBACK_ID):
        resp = client.post("/api/feedback", json={
            "document_id": SAMPLE_DOC_ID,
            "element_id": 1,
            "page_id": 0,
            "is_correct": True,
        })
        assert resp.status_code == 200


def test_get_document_feedback(client):
    with patch("api.feedback.feedback_db.get_feedback_for_document", return_value=[
        {"feedback_id": SAMPLE_FEEDBACK_ID, "element_id": 2, "is_correct": False},
    ]):
        resp = client.get(f"/api/feedback/document/{SAMPLE_DOC_ID}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


def test_delete_feedback(client):
    with patch("api.feedback.feedback_db.delete_feedback"):
        resp = client.delete(f"/api/feedback/{SAMPLE_FEEDBACK_ID}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
