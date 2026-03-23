"""Tests for export/import endpoints."""

import io
import json
import zipfile
from unittest.mock import patch

from tests.conftest import SAMPLE_DOC_ID


def test_export_zip_structure(client, sample_parsed_result):
    doc = {
        "document_id": SAMPLE_DOC_ID,
        "filename": "invoice.pdf",
        "volume_path": "/Volumes/main/default/vol/invoice.pdf",
        "parsed_result": sample_parsed_result,
        "status": "parsed",
        "page_count": 2,
        "element_count": 4,
    }
    with patch("api.export.docs_db.get_document", return_value=doc):
        with patch("api.export.feedback_db.get_feedback_for_document", return_value=[]):
            with patch("api.export._download_file_from_volume", return_value=b"fake-content"):
                with patch("api.export.get_databricks_token", return_value="mock-token"):
                    resp = client.get(f"/api/export/document/{SAMPLE_DOC_ID}")
                    assert resp.status_code == 200
                    assert "application/zip" in resp.headers["content-type"]

                    # Verify ZIP structure
                    buf = io.BytesIO(resp.content)
                    with zipfile.ZipFile(buf) as zf:
                        names = zf.namelist()
                        assert "manifest.jsonl" in names
                        assert "parsed_result.json" in names
                        assert "source/invoice.pdf" in names


def test_export_manifest_structure(client, sample_parsed_result):
    doc = {
        "document_id": SAMPLE_DOC_ID,
        "filename": "test.pdf",
        "volume_path": "/Volumes/main/default/vol/test.pdf",
        "parsed_result": sample_parsed_result,
        "status": "parsed",
        "page_count": 2,
        "element_count": 4,
    }
    with patch("api.export.docs_db.get_document", return_value=doc):
        with patch("api.export.feedback_db.get_feedback_for_document", return_value=[]):
            with patch("api.export._download_file_from_volume", return_value=None):
                with patch("api.export.get_databricks_token", return_value="mock-token"):
                    resp = client.get(f"/api/export/document/{SAMPLE_DOC_ID}")
                    buf = io.BytesIO(resp.content)
                    with zipfile.ZipFile(buf) as zf:
                        manifest = zf.read("manifest.jsonl").decode("utf-8")
                        lines = [json.loads(l) for l in manifest.strip().split("\n")]

                        types = [l["type"] for l in lines]
                        assert "metadata" in types
                        assert "element" in types
                        assert "summary" in types

                        meta = next(l for l in lines if l["type"] == "metadata")
                        assert meta["filename"] == "test.pdf"
                        assert meta["parse_version"] == "2.0"


def test_import_zip(client):
    # Build a minimal valid ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = json.dumps({
            "type": "metadata",
            "filename": "imported.pdf",
            "parse_version": "2.0",
            "page_count": 1,
            "element_count": 1,
        }) + "\n" + json.dumps({
            "type": "element",
            "element_id": 0,
            "page_id": 0,
            "element_type": "text",
            "bbox": [10, 20, 300, 40],
            "content": "Hello",
            "feedback": {
                "is_correct": True,
                "issue_category": None,
                "comment": None,
                "suggested_content": None,
                "suggested_type": None,
                "reviewer": None,
            },
        }) + "\n" + json.dumps({"type": "summary", "total_elements": 1, "elements_reviewed": 1})
        zf.writestr("manifest.jsonl", manifest)
        zf.writestr("parsed_result.json", json.dumps({"document": {"pages": [], "elements": []}}))

    buf.seek(0)

    with patch("api.export.docs_db.insert_document", return_value="new-id"):
        with patch("api.export.docs_db.update_document_status"):
            with patch("api.export.feedback_db.upsert_feedback", return_value="fb-id"):
                resp = client.post(
                    "/api/export/import",
                    files={"file": ("bundle.zip", buf.getvalue(), "application/zip")},
                )
                assert resp.status_code == 200
                data = resp.json()
                # Import is now always async — returns processing status
                assert data["status"] == "processing"
                assert "import_id" in data
