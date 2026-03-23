"""Tests for config.py."""

from config import parse_volume_path


def test_valid_volume_path():
    result = parse_volume_path("/Volumes/main/default/my_volume")
    assert result == {
        "catalog": "main",
        "schema": "default",
        "volume_name": "my_volume",
        "full_path": "/Volumes/main/default/my_volume",
    }


def test_invalid_path_too_short():
    assert parse_volume_path("/Volumes/main") is None


def test_missing_volumes_prefix():
    assert parse_volume_path("/data/main/default/vol") is None
