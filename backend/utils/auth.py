"""
Authentication utilities for Databricks Apps.

Dual-mode OAuth: Databricks Apps (client credentials) or local CLI profile.
Handles OAuth token generation using client credentials flow (Apps)
or profile-based authentication (local testing).
"""

import os
import time
import logging
import subprocess
import json as json_module
from typing import Optional

import requests
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

_token_cache = {"token": None, "expires_at": 0}
_is_local_mode = None
_workspace_client = None


def get_databricks_token() -> str:
    """Get Databricks OAuth token (Apps mode or local profile)."""
    global _is_local_mode

    current_time = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > current_time:
        return _token_cache["token"]

    host = os.environ.get("DATABRICKS_HOST")
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")

    if not all([host, client_id, client_secret]):
        if _is_local_mode is None:
            _is_local_mode = True
            logger.info("OAuth credentials not available - using local profile authentication")
        return _get_token_from_sdk_profile()

    if host.startswith("http://") or host.startswith("https://"):
        host = host.split("://")[1]

    token_url = f"https://{host}/oidc/v1/token"

    response = requests.post(
        token_url,
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    token_data = response.json()

    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        raise Exception("No access_token in OAuth response")

    _token_cache["token"] = access_token
    _token_cache["expires_at"] = current_time + expires_in - 300

    logger.info(f"Obtained OAuth token (expires in {expires_in}s)")
    return access_token


def _get_token_from_sdk_profile() -> str:
    """Get token via Databricks CLI profile (local dev)."""
    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")
    w = WorkspaceClient()
    host = w.config.host

    cmd = ["databricks", "auth", "token", "--host", host, "--profile", profile]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        raise Exception(f"databricks auth token failed: {result.stderr}")

    token_data = json_module.loads(result.stdout)
    access_token = token_data.get("access_token")

    if not access_token:
        raise Exception("No access_token in CLI response")

    current_time = time.time()
    _token_cache["token"] = access_token
    _token_cache["expires_at"] = current_time + 3600 - 300

    return access_token


def get_workspace_client() -> WorkspaceClient:
    """Get or create a WorkspaceClient singleton."""
    global _workspace_client
    if _workspace_client is None:
        _workspace_client = WorkspaceClient()
    return _workspace_client


def get_workspace_url() -> str:
    """Get the workspace URL with https:// prefix."""
    host = os.environ.get("DATABRICKS_HOST", "")
    if not host.startswith("http"):
        host = f"https://{host}"
    return host
