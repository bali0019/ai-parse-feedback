"""Lakebase (Postgres) connection using OAuth credentials.

Provisioned Lakebase requires an OAuth token as the password.
Uses the REST API for credential generation (works with any SDK version).
Creates fresh connections per request to avoid stale tokens.
"""

import os
import logging
from contextlib import contextmanager

import requests
import psycopg2
import psycopg2.extras

from config import PGHOST, PGPORT, PGUSER, PGDATABASE, PGSSLMODE

logger = logging.getLogger(__name__)


def _get_oauth_password() -> str:
    """Generate an OAuth token via REST API to use as Postgres password."""
    import uuid
    from utils.auth import get_databricks_token, get_workspace_url

    instance_name = os.environ.get("LAKEBASE_INSTANCE_NAME", "ai-parse-feedback-db")
    token = get_databricks_token()
    workspace_url = get_workspace_url()

    resp = requests.post(
        f"{workspace_url}/api/2.0/database/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "instance_names": [instance_name],
            "request_id": str(uuid.uuid4()),
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _connect() -> psycopg2.extensions.connection:
    """Create a new Lakebase connection with a fresh OAuth token."""
    password = _get_oauth_password()
    logger.info(f"Connecting to Lakebase: {PGHOST}:{PGPORT}/{PGDATABASE} as {PGUSER}")
    return psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        database=PGDATABASE,
        user=PGUSER,
        password=password,
        sslmode=PGSSLMODE,
    )


@contextmanager
def get_connection():
    """Get a Lakebase connection (context manager). Fresh connection each time."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor():
    """Get a cursor with RealDictCursor (context manager)."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cursor
        finally:
            cursor.close()
