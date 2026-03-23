"""Tests for API document endpoints."""

from unittest.mock import patch, MagicMock
from tests.conftest import SAMPLE_DOC_ID


def test_list_documents(client):
    with patch("api.documents.docs_db.list_documents", return_value=[]):
        with patch("api.documents.docs_db.get_document_feedback_stats", return_value={"total_feedback": 0, "correct_count": 0, "issue_count": 0}):
            resp = client.get("/api/documents")
            assert resp.status_code == 200
            assert resp.json() == []


def test_get_config(client):
    resp = client.get("/api/documents/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "issue_categories" in data
    assert "element_colors" in data
    assert len(data["issue_categories"]) == 15


def test_upload_document(client):
    with patch("api.documents.upload_to_volume") as mock_upload:
        mock_upload.return_value = {
            "volume_path": "/Volumes/main/default/vol/test.pdf",
            "safe_filename": "test.pdf",
            "size_bytes": 100,
            "file_hash_sha256": "abc123",
        }
        with patch("api.documents.docs_db.insert_document", return_value=SAMPLE_DOC_ID):
            resp = client.post(
                "/api/documents/upload",
                files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["document_id"] == SAMPLE_DOC_ID
            assert data["status"] == "uploaded"


def test_upload_empty_file(client):
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_trigger_parse(client):
    doc = {
        "document_id": SAMPLE_DOC_ID,
        "filename": "test.pdf",
        "volume_path": "/Volumes/main/default/vol/test.pdf",
        "status": "uploaded",
    }
    with patch("api.documents.docs_db.get_document", return_value=doc):
        with patch("api.documents.docs_db.update_document_status"):
            resp = client.post(f"/api/documents/{SAMPLE_DOC_ID}/parse")
            assert resp.status_code == 200
            assert resp.json()["status"] == "parsing"


def test_get_document(client, sample_document):
    serialized = {k: (str(v) if hasattr(v, 'hex') else v.isoformat() if hasattr(v, 'isoformat') else v)
                  for k, v in sample_document.items()}
    with patch("api.documents.docs_db.get_document", return_value=serialized):
        with patch("api.documents.docs_db.get_document_feedback_stats",
                    return_value={"total_feedback": 0, "correct_count": 0, "issue_count": 0}):
            resp = client.get(f"/api/documents/{SAMPLE_DOC_ID}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["filename"] == "invoice.pdf"


def test_get_page_data(client, sample_parsed_result):
    doc = {
        "document_id": SAMPLE_DOC_ID,
        "parsed_result": sample_parsed_result,
        "status": "parsed",
    }
    with patch("api.documents.docs_db.get_document", return_value=doc):
        with patch("api.documents.feedback_db.get_feedback_for_page", return_value=[]):
            with patch("api.documents.load_page_image", return_value={
                "data_uri": "data:image/png;base64,abc",
                "width": 800,
                "height": 1000,
                "size_bytes": 1000,
            }):
                resp = client.get(f"/api/documents/{SAMPLE_DOC_ID}/page/0")
                assert resp.status_code == 200
                data = resp.json()
                assert data["page_id"] == 0
                assert data["total_pages"] == 2
                assert len(data["elements"]) == 3  # 3 elements on page 0


def test_delete_document(client):
    with patch("api.documents.docs_db.get_document", return_value={"document_id": SAMPLE_DOC_ID}):
        with patch("api.documents.docs_db.delete_document"):
            resp = client.delete(f"/api/documents/{SAMPLE_DOC_ID}")
            assert resp.status_code == 200
            assert resp.json()["status"] == "deleted"
