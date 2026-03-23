"""Tests for services layer (ingest, parse, image_loader)."""

import json
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from services.ingest import sanitize_filename, upload_to_volume
from services.image_loader import get_page_elements, load_page_image


# --- sanitize_filename ---

def test_sanitize_spaces():
    assert sanitize_filename("my file.pdf") == "my_file.pdf"


def test_sanitize_special_chars():
    assert sanitize_filename("doc (1) [final].pdf") == "doc__1___final_.pdf"


def test_sanitize_preserves_extension():
    result = sanitize_filename("hello world.TIFF")
    assert result.endswith(".TIFF")


# --- get_page_elements ---

def test_get_page_elements_filters_by_page(sample_parsed_result):
    page0 = get_page_elements(sample_parsed_result, 0)
    assert len(page0) == 3  # elements 0, 1, 2
    assert all(e["id"] in (0, 1, 2) for e in page0)

    page1 = get_page_elements(sample_parsed_result, 1)
    assert len(page1) == 1
    assert page1[0]["id"] == 3


def test_get_page_elements_empty_page(sample_parsed_result):
    result = get_page_elements(sample_parsed_result, 99)
    assert result == []


# --- upload_to_volume (mocked) ---

@patch("services.ingest.get_workspace_url", return_value="https://mock.databricks.com")
@patch("services.ingest.get_databricks_token", return_value="tok")
@patch("services.ingest.requests.put")
def test_upload_success(mock_put, _tok, _url):
    mock_put.return_value = MagicMock(status_code=200)
    result = upload_to_volume(b"hello", "test.pdf", "main", "default", "vol")
    assert result["volume_path"] == "/Volumes/main/default/vol/test.pdf"
    assert result["size_bytes"] == 5
    assert "file_hash_sha256" in result


@patch("services.ingest.get_workspace_url", return_value="https://mock.databricks.com")
@patch("services.ingest.get_databricks_token", return_value="tok")
@patch("services.ingest.requests.put")
def test_upload_failure(mock_put, _tok, _url):
    mock_put.return_value = MagicMock(status_code=500, text="Internal Server Error")
    with pytest.raises(Exception, match="Upload failed"):
        upload_to_volume(b"hello", "test.pdf", "main", "default", "vol")


# --- load_page_image (mocked) ---

@patch("services.image_loader.get_workspace_url", return_value="https://mock.databricks.com")
@patch("services.image_loader.get_databricks_token", return_value="tok")
@patch("services.image_loader.requests.get")
def test_load_page_image_success(mock_get, _tok, _url):
    # Create a tiny valid PNG
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (100, 50), color="red").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    mock_get.return_value = MagicMock(status_code=200, content=png_bytes)
    mock_get.return_value.raise_for_status = MagicMock()

    result = load_page_image("/Volumes/main/default/imgs/page_0.png")
    assert result is not None
    assert result["width"] == 100
    assert result["height"] == 50
    assert result["data_uri"].startswith("data:image/png;base64,")


def test_load_page_image_empty_uri():
    assert load_page_image("") is None
    assert load_page_image(None) is None
