"""Upload files to Unity Catalog Volume via Files API.

Upload files to Unity Catalog Volume via Files API.
"""

import os
import re
import hashlib
import logging

import requests

from utils.auth import get_databricks_token, get_workspace_url

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str) -> str:
    filename = filename.replace(" ", "_")
    name, ext = os.path.splitext(filename)
    name = re.sub(r"[^\w\-]", "_", name)
    return f"{name}{ext}"


def upload_to_volume(
    file_bytes: bytes,
    filename: str,
    catalog: str,
    schema: str,
    volume_name: str,
    overwrite: bool = True,
) -> dict:
    """Upload file to UC Volume. Returns dict with volume_path and metadata."""
    safe_filename = sanitize_filename(filename)
    volume_path = f"/Volumes/{catalog}/{schema}/{volume_name}/{safe_filename}"

    token = get_databricks_token()
    workspace_url = get_workspace_url()
    api_url = f"{workspace_url}/api/2.0/fs/files{volume_path}"

    response = requests.put(
        api_url,
        data=file_bytes,
        headers={"Authorization": f"Bearer {token}"},
        params={"overwrite": "true" if overwrite else "false"},
    )

    if response.status_code not in (200, 201, 204):
        raise Exception(f"Upload failed ({response.status_code}): {response.text}")

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.info(f"Uploaded {safe_filename} to {volume_path}")

    return {
        "volume_path": volume_path,
        "safe_filename": safe_filename,
        "size_bytes": len(file_bytes),
        "file_hash_sha256": file_hash,
    }


def delete_from_volume(volume_path: str) -> bool:
    """Delete a file from UC Volume. Returns True if deleted, False on error."""
    try:
        token = get_databricks_token()
        workspace_url = get_workspace_url()
        api_url = f"{workspace_url}/api/2.0/fs/files{volume_path}"
        response = requests.delete(api_url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code in (200, 204, 404):  # 404 = already gone, fine
            logger.info(f"Deleted from volume: {volume_path}")
            return True
        logger.warning(f"Failed to delete {volume_path}: {response.status_code}")
        return False
    except Exception as e:
        logger.warning(f"Error deleting {volume_path}: {e}")
        return False


def delete_directory_from_volume(dir_path: str) -> bool:
    """Delete a UC Volume directory by listing contents, deleting files, then removing empty dir."""
    try:
        token = get_databricks_token()
        workspace_url = get_workspace_url()
        headers = {"Authorization": f"Bearer {token}"}

        # List directory contents
        list_url = f"{workspace_url}/api/2.0/fs/directories{dir_path}"
        resp = requests.get(list_url, headers=headers)
        if resp.status_code == 404:
            return True  # Already gone
        if resp.status_code != 200:
            logger.warning(f"Failed to list directory {dir_path}: {resp.status_code}")
            return False

        contents = resp.json().get("contents", [])
        for entry in contents:
            path = entry.get("path", "")
            if entry.get("is_directory"):
                delete_directory_from_volume(path)  # Recurse
            else:
                # Delete file
                file_url = f"{workspace_url}/api/2.0/fs/files{path}"
                requests.delete(file_url, headers=headers)

        # Now delete the empty directory
        requests.delete(list_url, headers=headers)
        logger.info(f"Deleted directory: {dir_path}")
        return True
    except Exception as e:
        logger.warning(f"Error deleting directory {dir_path}: {e}")
        return False
